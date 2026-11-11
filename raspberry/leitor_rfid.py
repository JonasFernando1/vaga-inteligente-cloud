"""Leitor RC522: abre por cartao autorizado e agenda fechamento apos 10s.

Antirrepeticao: um cartao mantido sobre o leitor nao reinicia a contagem.
Uma nova aproximacao exige que ele fique ausente pelo menos 1 segundo.
"""

import logging
import threading
from datetime import datetime
from time import monotonic

from mfrc522 import SimpleMFRC522
from banco import conectar, registrar_evento
from controlador import comandar_cancela, agendar_fechamento_rfid

log = logging.getLogger("rfid")
INTERVALO = 0.15
AUSENCIA_PARA_NOVA_LEITURA = 1.5


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class MonitorRFID:
    def __init__(self):
        self.parar = threading.Event()
        self.thread = None
        self.leitor = None
        self.lock = threading.Lock()
        self.ultima_leitura = None
        self.cartao_presente = None
        self.ultima_presenca = 0.0

    def iniciar(self):
        if self.thread and self.thread.is_alive():
            return
        self.leitor = SimpleMFRC522()
        self.parar.clear()
        self.thread = threading.Thread(
            target=self.executar, daemon=True, name="monitor-rfid"
        )
        self.thread.start()

    def processar(self, uid):
        with conectar() as db:
            cartao = db.execute(
                "SELECT nome, autorizado FROM cartoes_rfid WHERE uid=?", (uid,)
            ).fetchone()
            lotacao = db.execute(
                "SELECT COUNT(*) FROM vagas WHERE ocupada=1"
            ).fetchone()[0]

        if not cartao or not cartao["autorizado"]:
            nome, status, mensagem = "Desconhecido", "NEGADO", "Cartão não autorizado"
        elif lotacao >= 2:
            nome, status, mensagem = cartao["nome"], "LOTADO", "Estacionamento lotado"
        else:
            nome = cartao["nome"]
            resultado = comandar_cancela("abrir", origem=f"RFID UID {uid}")
            if resultado.get("sucesso"):
                agendado = agendar_fechamento_rfid()
                status = "AUTORIZADO"
                mensagem = (
                    "Acesso autorizado; fechamento agendado em 10s "
                    "(TESTE DE BANCADA SEM SENSOR)."
                    if agendado else "Acesso autorizado; sem fechamento automático habilitado."
                )
            else:
                status = "FALHA_ABERTURA"
                mensagem = "Cartão autorizado, mas " + resultado["mensagem"]

        leitura = {
            "uid": uid,
            "nome": nome,
            "status": status,
            "mensagem": mensagem,
            "horario": agora(),
        }
        registrar_evento("RFID", f"{mensagem} | {nome} | UID: {uid}")
        with self.lock:
            self.ultima_leitura = leitura
        log.info("RFID: %s - %s", uid, status)

    def executar(self):
        while not self.parar.is_set():
            try:
                uid_lido = self.leitor.read_id_no_block()
                instante = monotonic()
                if uid_lido is None:
                    if instante - self.ultima_presenca >= AUSENCIA_PARA_NOVA_LEITURA:
                        self.cartao_presente = None
                else:
                    uid = str(uid_lido)
                    self.ultima_presenca = instante
                    if uid != self.cartao_presente:
                        self.cartao_presente = uid
                        self.processar(uid)
                        # Nao contabilizar o tempo gasto abrindo o servo
                        # como se o cartao tivesse sido retirado.
                        self.ultima_presenca = monotonic()
            except Exception:
                log.exception("Falha na leitura/processamento de cartão")
                self.parar.wait(1.0)
            self.parar.wait(INTERVALO)

    def encerrar(self):
        self.parar.set()
        if self.thread:
            self.thread.join(timeout=3)
        # Nao executar GPIO.cleanup() global.

    def status(self):
        with self.lock:
            ultima = dict(self.ultima_leitura) if self.ultima_leitura else None
        return {
            "monitor_ativo": bool(self.thread and self.thread.is_alive()),
            "ultima_leitura": ultima,
        }


monitor_rfid = MonitorRFID()
