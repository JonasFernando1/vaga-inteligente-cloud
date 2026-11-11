
import logging
import threading
from time import monotonic, sleep

from gpiozero import DigitalInputDevice
from banco import atualizar_vaga, listar_vagas

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sensores_ir")

# BCM: GPIO 17 = vaga 1; GPIO 27 = vaga 2
# False significa que LOW (0) representa ocupação.
# A polaridade do sensor 2 ainda precisa ser confirmada.
CONFIG = {
    1: {"gpio": 17, "ocupado_em_high": False},
    2: {"gpio": 27, "ocupado_em_high": False},
}

INTERVALO = 0.1
DEBOUNCE = 0.5


class MonitorIR:
    def __init__(self):
        self.parar = threading.Event()
        self.thread = None
        self.sensores = {}
        self.estavel = {}
        self.candidato = {}
        self.desde = {}

    def iniciar(self):
        if self.thread and self.thread.is_alive():
            return

        try:
            for vaga, config in CONFIG.items():
                self.sensores[vaga] = DigitalInputDevice(
                    config["gpio"],
                    pull_up=False
                )
        except Exception:
            for sensor in self.sensores.values():
                sensor.close()
            self.sensores.clear()
            raise

        self.parar.clear()
        self.thread = threading.Thread(
            target=self.executar,
            daemon=True,
            name="monitor-ir"
        )
        self.thread.start()

    def ler(self, vaga):
        nivel = bool(self.sensores[vaga].value)
        return nivel == CONFIG[vaga]["ocupado_em_high"]

    def executar(self):
        try:
            # Lê o estado inicial e aguarda estabilização.
            for vaga in CONFIG:
                self.candidato[vaga] = self.ler(vaga)
                self.desde[vaga] = monotonic()
                self.estavel[vaga] = None

            while not self.parar.is_set():
                instante = monotonic()

                for vaga in CONFIG:
                    leitura = self.ler(vaga)

                    if leitura != self.candidato[vaga]:
                        self.candidato[vaga] = leitura
                        self.desde[vaga] = instante

                    if (
                        instante - self.desde[vaga] >= DEBOUNCE
                        and leitura != self.estavel[vaga]
                    ):
                        # Só atualiza o estado confirmado.
                        try:
                            alterou = atualizar_vaga(vaga, leitura)
                            self.estavel[vaga] = leitura

                            if alterou:
                                log.info(
                                    "Vaga %s: %s",
                                    vaga,
                                    "OCUPADA" if leitura else "LIVRE"
                                )
                        except Exception:
                            log.exception(
                                "Erro ao atualizar vaga %s", vaga
                            )

                self.parar.wait(INTERVALO)

        except Exception:
            log.exception("Falha no monitoramento IR")
        finally:
            for sensor in self.sensores.values():
                sensor.close()
            self.sensores.clear()

    def encerrar(self):
        self.parar.set()
        if self.thread:
            self.thread.join(timeout=3)

    def status(self):
        return {
            "monitor_ativo": bool(
                self.thread and self.thread.is_alive()
            ),
            "vagas": listar_vagas()
        }


monitor_ir = MonitorIR()
