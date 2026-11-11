"""Leitura das vagas por IR: BCM17 e BCM27 (LOW = ocupada).

Sem sensor/sem GPIO válido não altera vagas no banco.
"""
import logging
import threading
from time import monotonic

from banco import atualizar_vaga

log = logging.getLogger("sensores-ir")
PINOS = {1: 17, 2: 27}
INTERVALO = 0.1
DEBOUNCE = 0.5


class MonitorIR:
    def __init__(self):
        self.parar = threading.Event()
        self.thread = None
        self.sensores = {}
        self.lock = threading.Lock()
        self.estados = {1: None, 2: None}
        self.erro = None

    def iniciar(self):
        if self.thread and self.thread.is_alive():
            return
        self.parar.clear()
        self.thread = threading.Thread(target=self.executar, name="monitor-ir", daemon=True)
        self.thread.start()

    def executar(self):
        try:
            from gpiozero import DigitalInputDevice
            for vaga_id, pino in PINOS.items():
                self.sensores[vaga_id] = DigitalInputDevice(pino, pull_up=False)
            candidatos = {}
            alterados_em = {}
            while not self.parar.is_set():
                instante = monotonic()
                for vaga_id, sensor in self.sensores.items():
                    # Pino LOW = carro na vaga; HIGH = vaga livre.
                    ocupado = not bool(sensor.value)
                    if candidatos.get(vaga_id) != ocupado:
                        candidatos[vaga_id] = ocupado
                        alterados_em[vaga_id] = instante
                    elif instante - alterados_em.get(vaga_id, instante) >= DEBOUNCE:
                        with self.lock:
                            anterior = self.estados[vaga_id]
                        if anterior is None or ocupado != anterior:
                            atualizar_vaga(vaga_id, ocupado)
                            with self.lock:
                                self.estados[vaga_id] = ocupado
                self.parar.wait(INTERVALO)
        except Exception as erro:
            with self.lock:
                self.erro = str(erro)
            log.exception("Monitor de IR interrompido")
        finally:
            for sensor in self.sensores.values():
                try:
                    sensor.close()
                except Exception:
                    pass
            self.sensores.clear()

    def encerrar(self):
        self.parar.set()
        if self.thread:
            self.thread.join(timeout=3)

    def status(self):
        with self.lock:
            return {
                "monitor_ativo": bool(self.thread and self.thread.is_alive()),
                "pinos_bcm": PINOS,
                "vagas_ocupadas_por_ir": dict(self.estados),
                "ultimo_erro": self.erro,
            }


monitor_ir = MonitorIR()
