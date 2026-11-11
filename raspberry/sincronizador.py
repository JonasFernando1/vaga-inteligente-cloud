"""Ponte entre a API local do Raspberry e o Supabase.

Roda como processo separado (vaga-sync.service). Não usa GPIO nem o SQLite:
conversa só por HTTP com a API local (127.0.0.1:8000) e com o Supabase.

  - envia o estado das vagas quando muda (e a cada 60 s, por garantia);
  - envia um sinal de vida com a posição da cancela a cada 10 s;
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
INTERVALO_SINAL = 10.0     # sinal de vida para o dashboard
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

    def enviar_vagas(self, vagas):
        corpo = [{
            "vaga_id": v["id"],
            "ocupada": bool(v["ocupada"]),
            "entrada": v["entrada"] if v["ocupada"] else None,
            "atualizado_em": agora_iso(),
        } for v in vagas]
        self._req(
            "POST", "/rest/v1/status_vagas",
            params={"on_conflict": "vaga_id"},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=corpo,
        )

    def sinal_de_vida(self, api_online, cancela_aberta, fechamento_habilitado):
        self._req("POST", "/rest/v1/rpc/fn_sinal_de_vida", json={
            "p_api_online": api_online,
            "p_cancela_aberta": cancela_aberta,
            "p_fechamento_habilitado": fechamento_habilitado,
        })

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

    def get(self, rota):
        r = requests.get(self.base + rota, timeout=TIMEOUT)
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
        self.proxima = {"comandos": 0.0, "vagas": 0.0, "sinal": 0.0}
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

    def enviar_sinal(self):
        try:
            cancela = self.api.get("/cancela/status")
            api_online = True
            aberta = cancela.get("cancela_aberta")
            habilitado = bool(cancela.get("fechamento_habilitado"))
            self._ok("API local (cancela)")
        except requests.RequestException as erro:
            self._falhou("API local (cancela)", erro)
            api_online, aberta, habilitado = False, None, False
        try:
            self.supabase.sinal_de_vida(api_online, aberta, habilitado)
            self._ok("Supabase (sinal de vida)")
        except requests.RequestException as erro:
            self._falhou("Supabase (sinal de vida)", erro)

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
        # Atualiza a posição da cancela no dashboard logo em seguida.
        self.proxima["sinal"] = 0.0

    def rodar(self):
        log.info("Sincronizador iniciado (API local: %s)", self.api.base)
        tarefas = {
            "comandos": (INTERVALO_COMANDOS, self.executar_comandos),
            "vagas": (INTERVALO_VAGAS, self.sincronizar_vagas),
            "sinal": (INTERVALO_SINAL, self.enviar_sinal),
        }
        while True:
            agora = time.monotonic()
            for nome, (intervalo, tarefa) in tarefas.items():
                if agora >= self.proxima[nome]:
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
