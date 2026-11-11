"""RC522 com reconexão: falhas no boot não derrubam a API.

Cartão autorizado abre a cancela. Fechamento após 10s só ocorre no modo
provisório de bancada explicitamente habilitado no controlador.py.
"""
import logging
import threading
from datetime import datetime
from time import monotonic

from banco import conectar, registrar_evento
from controlador import comandar_cancela, agendar_fechamento_rfid

log = logging.getLogger("rfid")
INTERVALO = 0.15
TEMPO_RECONEXAO = 3.0
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
        self.leitor_conectado = False
        self.ultimo_erro = None
        self.tentativas_reconexao = 0

    def iniciar(self):
        if self.thread and self.thread.is_alive():
            return
        self.parar.clear()
        self.thread = threading.Thread(
            target=self.executar, name="monitor-rfid", daemon=True
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
            nome = cartao["nome"] if cartao else "Desconhecido"
            status, mensagem = "NEGADO", "Cartão não autorizado"
        elif lotacao >= 2:
            nome, status, mensagem = cartao["nome"], "LOTADO", "Estacionamento lotado"
        else:
            nome = cartao["nome"]
            resultado = comandar_cancela("abrir", origem=f"RFID UID {uid}")
            if resultado.get("sucesso"):
                agendado = agendar_fechamento_rfid()
                status = "AUTORIZADO"
                mensagem = (
                    "Acesso autorizado; fechamento de bancada em 10s agendado"
                    if agendado else
                    "Acesso autorizado; fechamento automático sem sensor desabilitado"
                )
            else:
                status = "FALHA_ABERTURA"
                mensagem = "Cartão autorizado, mas " + resultado.get("mensagem", "falhou")

        leitura = {
            "uid": uid, "nome": nome, "status": status,
            "mensagem": mensagem, "horario": agora(),
        }
        registrar_evento("RFID", f"{mensagem} | {nome} | UID: {uid}")
        with self.lock:
            self.ultima_leitura = leitura
        log.info("RFID lido: status=%s", status)

    def executar(self):
        # Inicialização NO thread permite que a API suba mesmo quando
        # o SPI/RC522 ainda não estiver pronto após o boot.
        while not self.parar.is_set():
            if self.leitor is None:
                try:
                    from mfrc522 import SimpleMFRC522
                    self.leitor = SimpleMFRC522()
                    with self.lock:
                        self.leitor_conectado = True
                        self.ultimo_erro = None
                    log.info("RC522 inicializado")
                except Exception as erro:
                    log.exception("Não foi possível iniciar RC522; nova tentativa em 3s")
                    with self.lock:
                        self.leitor_conectado = False
                        self.ultimo_erro = f"{type(erro).__name__}: {erro}"
                        self.tentativas_reconexao += 1
                    self.parar.wait(TEMPO_RECONEXAO)
                    continue
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
                        # Ignora o tempo que o SG90 levou para mover a haste.
                        self.ultima_presenca = monotonic()
            except Exception as erro:
                log.exception("Falha de leitura RC522; tentando reconectar")
                with self.lock:
                    self.leitor_conectado = False
                    self.ultimo_erro = f"{type(erro).__name__}: {erro}"
                    self.tentativas_reconexao += 1
                self.leitor = None
                self.cartao_presente = None
                self.parar.wait(TEMPO_RECONEXAO)
                continue
            self.parar.wait(INTERVALO)
        self.leitor = None
        with self.lock:
            self.leitor_conectado = False

    def encerrar(self):
        self.parar.set()
        if self.thread:
            self.thread.join(timeout=5)
        # Nunca executar GPIO.cleanup() global: IR e servo compartilham GPIOs.

    def status(self):
        with self.lock:
            return {
                "monitor_ativo": bool(self.thread and self.thread.is_alive()),
                "leitor_conectado": self.leitor_conectado,
                "ultimo_erro": self.ultimo_erro,
                "tentativas_reconexao": self.tentativas_reconexao,
                "ultima_leitura": (
                    dict(self.ultima_leitura) if self.ultima_leitura else None
                ),
            }


monitor_rfid = MonitorRFID()
