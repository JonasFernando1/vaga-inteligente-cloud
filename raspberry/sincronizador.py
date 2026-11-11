"""Ponte entre a API local do Raspberry e o Supabase.

Roda como processo separado (vaga-sync.service). Não usa GPIO nem o SQLite:
conversa só por HTTP com a API local (127.0.0.1:8000) e com o Supabase.

  - envia o estado das vagas quando muda (e a cada 60 s, por garantia);
  - envia o status da cancela e do leitor RFID quando muda (e um sinal de
    vida a cada 10 s, para o dashboard saber que o Pi está online);
  - copia os eventos e as permanências novas do SQLite (via API);
  - busca comandos da cancela pedidos no dashboard online e os executa
    pela própria API local, que mantém todas as travas de segurança
    (o fechamento continua bloqueado sem VAGA_FECHAMENTO_TESTE=1).

Se a internet ou a API cair, ele só registra no log e tenta de novo:
sensores, RFID e cancela local continuam funcionando sem ele.

Configuração (variáveis de ambiente ou arquivo .env.supabase ao lado deste script):
  SUPABASE_URL         https://SEU-PROJETO.supabase.co
  SUPABASE_SECRET_KEY  chave secreta (service_role / sb_secret_...)
  VAGA_API             padrão http://127.0.0.1:8000
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("sincronizador")

INTERVALO_COMANDOS = 1.5   # s entre buscas de comando
INTERVALO_VAGAS = 2.0      # s entre leituras das vagas na API local
REENVIO_VAGAS = 60.0       # reenvia as vagas mesmo sem mudança
INTERVALO_STATUS = 2.0     # s entre leituras da cancela/RFID na API local
SINAL_DE_VIDA = 10.0       # envia o status mesmo sem mudança
INTERVALO_HISTORICO = 5.0  # s entre cópias de eventos/permanências
LIMITE_HISTORICO = 100     # linhas mais recentes conferidas a cada vez
TIMEOUT = 8


def agora_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def carregar_env(caminho: Path):
    """Lê KEY=VALOR de um arquivo simples, sem sobrescrever o ambiente."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


class Supabase:
    def __init__(self, url, chave):
        self.base = url.rstrip("/")
        self.sessao = requests.Session()
        self.sessao.headers.update({
            "apikey": chave,
            "Authorization": f"Bearer {chave}",
            "Content-Type": "application/json",
        })

    def _req(self, metodo, rota, **kwargs):
        r = self.sessao.request(metodo, self.base + rota, timeout=TIMEOUT, **kwargs)
        r.raise_for_status()
        return r.json() if r.content else None

    def _upsert(self, tabela, linhas, conflito, ignorar_duplicadas=False):
        resolucao = "ignore-duplicates" if ignorar_duplicadas else "merge-duplicates"
        self._req(
            "POST", f"/rest/v1/{tabela}",
            params={"on_conflict": conflito},
            headers={"Prefer": f"resolution={resolucao},return=minimal"},
            json=linhas,
        )

    def enviar_vagas(self, vagas):
        self._upsert("status_vagas", [{
            "vaga_id": v["id"],
            "ocupada": bool(v["ocupada"]),
            "entrada": v["entrada"] if v["ocupada"] else None,
            "atualizado_em": agora_iso(),
        } for v in vagas], "vaga_id")

    def enviar_eventos(self, eventos):
        self._upsert("eventos", [{
            "id_local": e["id"],
            "horario": e["horario"],
            "tipo": e["tipo"],
            "descricao": e["descricao"],
        } for e in eventos], "id_local,horario", ignorar_duplicadas=True)

    def enviar_permanencias(self, permanencias):
        self._upsert("permanencias", [{
            "id_local": p["id"],
            "vaga_id": p["vaga_id"],
            "entrada": p["entrada"],
            "saida": p["saida"],
            "duracao_segundos": p["duracao_segundos"],
        } for p in permanencias], "id_local,saida", ignorar_duplicadas=True)

    def enviar_ultima_leitura(self, leitura):
        self._upsert("status_privado", [{
            "id": 1,
            "rfid_ultima_leitura": leitura,
            "atualizado_em": agora_iso(),
        }], "id")

    def sinal_de_vida(self, status):
        self._req("POST", "/rest/v1/rpc/fn_sinal_de_vida", json=status)

    def pegar_comando(self):
        resultado = self._req("POST", "/rest/v1/rpc/fn_pegar_comando_cancela", json={})
        return resultado[0] if resultado else None

    def concluir_comando(self, comando_id, status, mensagem):
        self._req(
            "PATCH", "/rest/v1/comandos_cancela",
            params={"id": f"eq.{comando_id}"},
            headers={"Prefer": "return=minimal"},
            json={
                "status": status,
                "mensagem": (mensagem or "")[:500],
                "executado_em": agora_iso(),
            },
        )


class ApiLocal:
    def __init__(self, url):
        self.base = url.rstrip("/")

    def get(self, rota, **params):
        r = requests.get(self.base + rota, params=params or None, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    def post(self, rota):
        r = requests.post(self.base + rota, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()


class Sincronizador:
    def __init__(self, supabase: Supabase, api: ApiLocal):
        self.supabase = supabase
        self.api = api
        self.vagas_enviadas = None
        self.ultimo_envio_vagas = 0.0
        self.status_enviado = None
        self.ultimo_sinal = 0.0
        self.leitura_enviada = None
        # Chaves (id, horário) das linhas já confirmadas no Supabase.
        self.historico_enviado = {"eventos": set(), "permanencias": set()}
        self.proxima = {}
        self.falhas = {}

    def _falhou(self, etapa, erro):
        # Loga a primeira falha de uma sequência; repetições viram debug.
        if etapa not in self.falhas:
            log.warning("%s falhou: %s", etapa, erro)
        else:
            log.debug("%s ainda falhando: %s", etapa, erro)
        self.falhas[etapa] = erro

    def _ok(self, etapa):
        if self.falhas.pop(etapa, None) is not None:
            log.info("%s voltou a funcionar", etapa)

    # -- vagas ---------------------------------------------------------------
    def sincronizar_vagas(self):
        try:
            vagas = self.api.get("/vagas")
        except requests.RequestException as erro:
            self._falhou("API local (vagas)", erro)
            return
        self._ok("API local (vagas)")
        chave = [(v["id"], bool(v["ocupada"]), v["entrada"]) for v in vagas]
        agora = time.monotonic()
        if chave == self.vagas_enviadas and agora - self.ultimo_envio_vagas < REENVIO_VAGAS:
            return
        try:
            self.supabase.enviar_vagas(vagas)
        except requests.RequestException as erro:
            self._falhou("Supabase (vagas)", erro)
            return
        self._ok("Supabase (vagas)")
        if chave != self.vagas_enviadas:
            log.info("Vagas enviadas: %s", ", ".join(
                f"{i}={'ocupada' if o else 'livre'}" for i, o, _ in chave))
        self.vagas_enviadas = chave
        self.ultimo_envio_vagas = agora

    # -- cancela e RFID ------------------------------------------------------
    def _ler_status(self):
        """Monta o status a partir da API local; None nos campos que falharem."""
        status = {"p_api_online": False}
        try:
            cancela = self.api.get("/cancela/status")
            auto = cancela.get("fechamento_automatico_rfid") or {}
            status.update({
                "p_api_online": True,
                "p_cancela_aberta": cancela.get("cancela_aberta"),
                "p_fechamento_habilitado": bool(cancela.get("fechamento_habilitado")),
                "p_auto_estado": auto.get("estado"),
                "p_auto_modo_bancada": auto.get("modo_bancada_sem_sensor"),
                "p_auto_segundos_restantes": auto.get("segundos_restantes"),
            })
            self._ok("API local (cancela)")
        except requests.RequestException as erro:
            self._falhou("API local (cancela)", erro)
        leitura = None
        try:
            rfid = self.api.get("/rfid/status")
            status.update({
                "p_rfid_monitor_ativo": rfid.get("monitor_ativo"),
                "p_rfid_leitor_conectado": rfid.get("leitor_conectado"),
                "p_rfid_ultimo_erro": rfid.get("ultimo_erro"),
            })
            ultima = rfid.get("ultima_leitura")
            if ultima:
                # O UID fica só no Pi e nos eventos; aqui basta o que a tela mostra.
                leitura = {k: ultima.get(k) for k in ("nome", "status", "mensagem", "horario")}
            self._ok("API local (RFID)")
        except requests.RequestException as erro:
            self._falhou("API local (RFID)", erro)
        return status, leitura

    def sincronizar_status(self):
        status, leitura = self._ler_status()
        # A contagem regressiva muda a cada leitura; só o início/fim dela conta como mudança.
        comparar = {k: v for k, v in status.items() if k != "p_auto_segundos_restantes"}
        comparar["contando"] = status.get("p_auto_segundos_restantes") is not None
        agora = time.monotonic()
        if comparar != self.status_enviado or agora - self.ultimo_sinal >= SINAL_DE_VIDA:
            try:
                self.supabase.sinal_de_vida(status)
                self._ok("Supabase (status)")
                self.status_enviado = comparar
                self.ultimo_sinal = agora
            except requests.RequestException as erro:
                self._falhou("Supabase (status)", erro)

        if leitura and leitura != self.leitura_enviada:
            try:
                self.supabase.enviar_ultima_leitura(leitura)
                self._ok("Supabase (último cartão)")
                self.leitura_enviada = leitura
                log.info("Leitura RFID enviada: %s", leitura.get("status"))
            except requests.RequestException as erro:
                self._falhou("Supabase (último cartão)", erro)

    # -- histórico -----------------------------------------------------------
    def _copiar(self, nome, rota, chave_tempo, enviar):
        try:
            linhas = self.api.get(rota, limite=LIMITE_HISTORICO)
        except requests.RequestException as erro:
            self._falhou(f"API local ({nome})", erro)
            return
        self._ok(f"API local ({nome})")
        chaves = {(l["id"], l[chave_tempo]) for l in linhas}
        novas = [l for l in linhas if (l["id"], l[chave_tempo]) not in self.historico_enviado[nome]]
        if not novas:
            return
        try:
            # Na primeira vez, reenvia as últimas linhas: duplicadas são ignoradas.
            enviar(novas)
        except requests.RequestException as erro:
            self._falhou(f"Supabase ({nome})", erro)
            return
        self._ok(f"Supabase ({nome})")
        self.historico_enviado[nome] = chaves
        log.info("%s: %d linha(s) conferida(s)/enviada(s)", nome.capitalize(), len(novas))

    def sincronizar_historico(self):
        self._copiar("eventos", "/eventos", "horario", self.supabase.enviar_eventos)
        self._copiar("permanencias", "/permanencias", "saida", self.supabase.enviar_permanencias)

    # -- comandos da cancela -------------------------------------------------
    def executar_comandos(self):
        try:
            comando = self.supabase.pegar_comando()
        except requests.RequestException as erro:
            self._falhou("Supabase (comandos)", erro)
            return
        self._ok("Supabase (comandos)")
        if not comando:
            return

        acao = comando["acao"]
        log.info("Comando #%s recebido: %s", comando["id"], acao)
        try:
            resposta = self.api.post(f"/cancela/{acao}")
            status = "executado" if resposta.get("sucesso") else "recusado"
            mensagem = resposta.get("mensagem", "")
        except requests.RequestException as erro:
            status, mensagem = "erro", f"API local indisponível: {erro}"
        log.info("Comando #%s %s: %s", comando["id"], status, mensagem)

        try:
            self.supabase.concluir_comando(comando["id"], status, mensagem)
        except requests.RequestException as erro:
            self._falhou("Supabase (resposta do comando)", erro)
        # Mostra a nova posição e o evento da cancela logo em seguida.
        self.proxima["status"] = 0.0
        self.proxima["historico"] = 0.0

    def rodar(self):
        log.info("Sincronizador iniciado (API local: %s)", self.api.base)
        tarefas = {
            "comandos": (INTERVALO_COMANDOS, self.executar_comandos),
            "vagas": (INTERVALO_VAGAS, self.sincronizar_vagas),
            "status": (INTERVALO_STATUS, self.sincronizar_status),
            "historico": (INTERVALO_HISTORICO, self.sincronizar_historico),
        }
        while True:
            agora = time.monotonic()
            for nome, (intervalo, tarefa) in tarefas.items():
                if agora >= self.proxima.get(nome, 0.0):
                    self.proxima[nome] = agora + intervalo
                    try:
                        tarefa()
                    except Exception:
                        log.exception("Erro inesperado em %s", nome)
            time.sleep(0.2)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    carregar_env(Path(__file__).resolve().parent / ".env.supabase")
    url = os.environ.get("SUPABASE_URL")
    chave = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not chave:
        raise SystemExit(
            "Defina SUPABASE_URL e SUPABASE_SECRET_KEY (veja .env.supabase.example)."
        )
    api = ApiLocal(os.environ.get("VAGA_API", "http://127.0.0.1:8000"))
    try:
        Sincronizador(Supabase(url, chave), api).rodar()
    except KeyboardInterrupt:
        log.info("Encerrado")


if __name__ == "__main__":
    main()
