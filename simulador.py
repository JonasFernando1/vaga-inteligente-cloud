"""API falsa do Raspberry para testar no PC, sem a placa.

Responde nas mesmas rotas e no mesmo formato da raspberry/api.py,
em http://127.0.0.1:8000, então o sincronizador roda igual roda no Pi:

    GET  /vagas            [{"id": 1, "ocupada": 0, "entrada": null}, ...]
    GET  /cancela/status   {"cancela_aberta": ..., "fechamento_habilitado": ...}
    POST /cancela/abrir    {"sucesso": true, "mensagem": "..."}
    POST /cancela/fechar   {"sucesso": ..., "mensagem": "..."}

Uso:
    python simulador.py                    # vagas mudam sozinhas a cada 8 a 20 s
    python simulador.py --sem-fechamento   # imita o Pi com VAGA_FECHAMENTO_TESTE=0
    python simulador.py --parado           # vagas só mudam pelo teclado

Com o simulador rodando, digite 1 ou 2 + Enter para trocar a vaga na hora.
Só usa a biblioteca padrão do Python.
"""
import argparse
import json
import random
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock = threading.Lock()
vagas = {1: {"ocupada": 0, "entrada": None}, 2: {"ocupada": 0, "entrada": None}}
cancela = {"aberta": False}
config = {"fechamento": True}


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def trocar_vaga(vaga_id):
    with lock:
        v = vagas[vaga_id]
        if v["ocupada"]:
            v["ocupada"], v["entrada"] = 0, None
        else:
            v["ocupada"], v["entrada"] = 1, agora()
        estado = "OCUPADA" if v["ocupada"] else "livre"
    print(f"[sim] vaga {vaga_id} -> {estado}")


def mexer_vagas_sozinho():
    while True:
        time.sleep(random.uniform(8, 20))
        trocar_vaga(random.choice([1, 2]))


def ler_teclado():
    while True:
        try:
            texto = input().strip()
        except EOFError:
            return
        if texto in ("1", "2"):
            trocar_vaga(int(texto))


class Handler(BaseHTTPRequestHandler):
    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        with lock:
            if self.path == "/vagas":
                return self._json([{"id": i, **v} for i, v in sorted(vagas.items())])
            if self.path == "/cancela/status":
                return self._json({
                    "cancela_aberta": cancela["aberta"],
                    "fechamento_habilitado": config["fechamento"],
                    "simulacao": True,
                })
        self._json({"detail": "Not Found"}, 404)

    def do_POST(self):
        if self.path == "/cancela/abrir":
            with lock:
                cancela["aberta"] = True
            print("[sim] cancela ABERTA")
            return self._json({"sucesso": True, "mensagem": "Comando de ABRIR enviado ao SG90 (simulado)."})
        if self.path == "/cancela/fechar":
            if not config["fechamento"]:
                print("[sim] fechar recusado (modo de teste desligado)")
                return self._json({"sucesso": False, "mensagem": "Ative o modo de teste para fechar fisicamente"})
            with lock:
                cancela["aberta"] = False
            print("[sim] cancela FECHADA")
            return self._json({"sucesso": True, "mensagem": "Comando de FECHAR enviado ao SG90 (simulado)."})
        self._json({"detail": "Not Found"}, 404)

    def log_message(self, *args):
        pass  # sem log de cada requisição


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sem-fechamento", action="store_true",
                        help="recusa o fechamento, como o Pi sem VAGA_FECHAMENTO_TESTE=1")
    parser.add_argument("--parado", action="store_true",
                        help="não muda as vagas sozinho")
    parser.add_argument("--porta", type=int, default=8000)
    args = parser.parse_args()
    config["fechamento"] = not args.sem_fechamento

    if not args.parado:
        threading.Thread(target=mexer_vagas_sozinho, daemon=True).start()
    threading.Thread(target=ler_teclado, daemon=True).start()

    servidor = ThreadingHTTPServer(("127.0.0.1", args.porta), Handler)
    print(f"[sim] API falsa em http://127.0.0.1:{args.porta}  (digite 1 ou 2 + Enter para trocar a vaga)")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n[sim] encerrado")


if __name__ == "__main__":
    main()
