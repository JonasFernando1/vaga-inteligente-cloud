"""API falsa do Raspberry para testar no PC, sem a placa.

Responde nas mesmas rotas e no mesmo formato da raspberry/api.py,
em http://127.0.0.1:8000, então o sincronizador roda igual roda no Pi:

    GET  /vagas              [{"id": 1, "ocupada": 0, "entrada": null}, ...]
    GET  /cancela/status     {"cancela_aberta": ..., "fechamento_automatico_rfid": {...}}
    GET  /rfid/status        {"leitor_conectado": ..., "ultima_leitura": {...}}
    GET  /eventos?limite=N   [{"id", "horario", "tipo", "descricao"}, ...]
    GET  /permanencias?limite=N
    POST /cancela/abrir      {"sucesso": true, "mensagem": "..."}
    POST /cancela/fechar     {"sucesso": ..., "mensagem": "..."}

Uso:
    python simulador.py                    # vagas e cartões mudam sozinhos
    python simulador.py --sem-fechamento   # imita o Pi com VAGA_FECHAMENTO_TESTE=0
    python simulador.py --bancada          # imita o fechamento RFID de 10 s (bancada)
    python simulador.py --parado           # só muda pelo teclado

Com o simulador rodando, digite + Enter:
    1 ou 2   troca a vaga        c   passa um cartão sorteado

Os cartões e nomes são falsos. Só usa a biblioteca padrão do Python.
"""
import argparse
import json
import random
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ATRASO_RFID = 10.0
CARTOES = [  # (uid, nome, autorizado) — falsos
    ("1001", "Cartão de teste A", True),
    ("1002", "Cartão de teste B", True),
    ("2001", "Cartão bloqueado", False),
    ("9999", None, False),  # não cadastrado
]

lock = threading.RLock()
vagas = {1: {"ocupada": 0, "entrada": None}, 2: {"ocupada": 0, "entrada": None}}
cancela = {"aberta": None}
eventos = []
permanencias = []
rfid = {"ultima_leitura": None}
auto = {"estado": "inativo", "fecha_em": None, "cancelamento": None}
config = {"fechamento": True, "bancada": False}


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def registrar(tipo, descricao):
    with lock:
        eventos.append({
            "id": len(eventos) + 1, "horario": agora(),
            "tipo": tipo, "descricao": descricao,
        })


def trocar_vaga(vaga_id):
    with lock:
        v = vagas[vaga_id]
        if v["ocupada"]:
            saida = agora()
            inicio = datetime.fromisoformat(v["entrada"])
            permanencias.append({
                "id": len(permanencias) + 1, "vaga_id": vaga_id,
                "entrada": v["entrada"], "saida": saida,
                "duracao_segundos": max(0, int((datetime.fromisoformat(saida) - inicio).total_seconds())),
            })
            v["ocupada"], v["entrada"] = 0, None
            registrar("VAGA", f"Vaga {vaga_id} liberada")
        else:
            v["ocupada"], v["entrada"] = 1, agora()
            registrar("VAGA", f"Vaga {vaga_id} ocupada")
        estado = "OCUPADA" if v["ocupada"] else "livre"
    print(f"[sim] vaga {vaga_id} -> {estado}")


def cancelar_auto(motivo):
    with lock:
        if auto["cancelamento"] is not None:
            auto["cancelamento"].set()
            auto["cancelamento"] = None
            auto["fecha_em"] = None
            auto["estado"] = motivo


def comandar(acao, origem):
    """Imita controlador.comandar_cancela (sem a parte do servo)."""
    with lock:
        if not origem.startswith("RFID"):
            cancelar_auto("cancelado_pelo_dashboard")
        if acao == "fechar" and not config["fechamento"]:
            return {"sucesso": False, "mensagem": "Ative o modo de teste para fechar fisicamente"}
        cancela["aberta"] = acao == "abrir"
        registrar("CANCELA", f"SG90 comando {acao} ({origem}); PROTÓTIPO SEM SENSOR REAL")
    print(f"[sim] cancela {'ABERTA' if acao == 'abrir' else 'FECHADA'} ({origem})")
    if acao == "abrir":
        return {"sucesso": True, "mensagem": "Comando de ABRIR enviado ao SG90 (simulado)."}
    return {"sucesso": True, "mensagem": "Comando de FECHAR enviado ao SG90 (simulado)."}


def agendar_fechamento():
    if not (config["bancada"] and config["fechamento"]):
        return False
    with lock:
        cancelar_auto("reagendado")
        evento = threading.Event()
        auto.update(cancelamento=evento, estado="contagem_10_segundos",
                    fecha_em=time.monotonic() + ATRASO_RFID)

    def fechar_depois():
        if evento.wait(ATRASO_RFID):
            return
        with lock:
            if auto["cancelamento"] is not evento:
                return
            comandar("fechar", "RFID apos 10s (bancada)")
            auto.update(cancelamento=None, fecha_em=None, estado="fechado_teste_bancada")

    threading.Thread(target=fechar_depois, daemon=True).start()
    return True


def passar_cartao():
    uid, nome, autorizado = random.choice(CARTOES)
    with lock:
        lotado = sum(v["ocupada"] for v in vagas.values()) >= 2
    if nome is None or not autorizado:
        nome = nome or "Desconhecido"
        status, mensagem = "NEGADO", "Cartão não autorizado"
    elif lotado:
        status, mensagem = "LOTADO", "Estacionamento lotado"
    else:
        comandar("abrir", f"RFID UID {uid}")
        agendado = agendar_fechamento()
        status = "AUTORIZADO"
        mensagem = ("Acesso autorizado; fechamento de bancada em 10s agendado" if agendado
                    else "Acesso autorizado; fechamento automático sem sensor desabilitado")
    registrar("RFID", f"{mensagem} | {nome} | UID: {uid}")
    with lock:
        rfid["ultima_leitura"] = {"uid": uid, "nome": nome, "status": status,
                                  "mensagem": mensagem, "horario": agora()}
    print(f"[sim] cartão {nome}: {status}")


def mexer_sozinho(tarefa, minimo, maximo):
    while True:
        time.sleep(random.uniform(minimo, maximo))
        tarefa()


def ler_teclado():
    while True:
        try:
            texto = input().strip().lower()
        except EOFError:
            return
        if texto in ("1", "2"):
            trocar_vaga(int(texto))
        elif texto == "c":
            passar_cartao()


def status_cancela():
    with lock:
        restante = (round(max(0.0, auto["fecha_em"] - time.monotonic()), 1)
                    if auto["fecha_em"] is not None else None)
        return {
            "cancela_aberta": cancela["aberta"],
            "fechamento_habilitado": config["fechamento"],
            "fechamento_automatico_rfid": {
                "habilitado": config["bancada"] and config["fechamento"],
                "modo_bancada_sem_sensor": config["bancada"],
                "agendado": auto["cancelamento"] is not None,
                "segundos_restantes": restante,
                "estado": auto["estado"],
            },
            "simulacao": True,
        }


class Handler(BaseHTTPRequestHandler):
    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        url = urlparse(self.path)
        limite = int(parse_qs(url.query).get("limite", ["50"])[0])
        limite = max(1, min(limite, 500))
        with lock:
            if url.path == "/vagas":
                return self._json([{"id": i, **v} for i, v in sorted(vagas.items())])
            if url.path == "/cancela/status":
                return self._json(status_cancela())
            if url.path == "/rfid/status":
                return self._json({
                    "monitor_ativo": True, "leitor_conectado": True,
                    "ultimo_erro": None, "tentativas_reconexao": 0,
                    "ultima_leitura": rfid["ultima_leitura"],
                })
            if url.path == "/eventos":
                return self._json(list(reversed(eventos[-limite:])))
            if url.path == "/permanencias":
                return self._json(list(reversed(permanencias[-limite:])))
        self._json({"detail": "Not Found"}, 404)

    def do_POST(self):
        if self.path == "/cancela/abrir":
            return self._json(comandar("abrir", "dashboard"))
        if self.path == "/cancela/fechar":
            return self._json(comandar("fechar", "dashboard"))
        self._json({"detail": "Not Found"}, 404)

    def log_message(self, *args):
        pass  # sem log de cada requisição


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sem-fechamento", action="store_true",
                        help="recusa o fechamento, como o Pi sem VAGA_FECHAMENTO_TESTE=1")
    parser.add_argument("--bancada", action="store_true",
                        help="fecha sozinho 10 s depois de um cartão autorizado")
    parser.add_argument("--parado", action="store_true",
                        help="não muda vagas nem passa cartões sozinho")
    parser.add_argument("--porta", type=int, default=8000)
    args = parser.parse_args()
    config["fechamento"] = not args.sem_fechamento
    config["bancada"] = args.bancada

    if not args.parado:
        threading.Thread(target=mexer_sozinho, args=(lambda: trocar_vaga(random.choice([1, 2])), 8, 20),
                         daemon=True).start()
        threading.Thread(target=mexer_sozinho, args=(passar_cartao, 15, 35), daemon=True).start()
    threading.Thread(target=ler_teclado, daemon=True).start()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Handler)
    print(f"[sim] API falsa em http://127.0.0.1:{args.porta}")
    print("[sim] digite 1 ou 2 + Enter para trocar a vaga, c + Enter para passar um cartão")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[sim] encerrado")


if __name__ == "__main__":
    main()
