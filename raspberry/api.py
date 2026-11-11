"""API local (localhost:8000) para dashboard e hardware da maquete."""
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Body, FastAPI, Query

from banco import listar_eventos, listar_permanencias, listar_vagas
from controlador import (
    comandar_cancela, definir_obstaculo, inicializar_controle, obter_estado,
)
from leitor_rfid import monitor_rfid
from sensores_ir import monitor_ir
from servo_cancela import encerrar_servo

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("vaga-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_controle()
    # As threads têm seus próprios tratamentos de falha; API não depende
    # do RC522 estar pronto no exato instante do boot.
    monitor_ir.iniciar()
    monitor_rfid.iniciar()
    log.info("API iniciada; monitores IR/RFID ativos")
    try:
        yield
    finally:
        monitor_rfid.encerrar()
        monitor_ir.encerrar()
        encerrar_servo()


app = FastAPI(title="Vaga Inteligente", version="1.4", lifespan=lifespan)


@app.get("/")
def raiz():
    return {"aplicacao": "Vaga Inteligente", "versao": "1.4"}


@app.get("/status")
def status():
    return {
        "horario": datetime.now().astimezone().isoformat(timespec="seconds"),
        "vagas": listar_vagas(),
        "cancela": obter_estado(),
        "sensores": monitor_ir.status(),
        "rfid": monitor_rfid.status(),
    }


@app.get("/vagas")
def vagas():
    return listar_vagas()


@app.get("/permanencias")
def permanencias(limite: int = Query(50, ge=1, le=500)):
    return listar_permanencias(limite)


@app.get("/eventos")
def eventos(limite: int = Query(50, ge=1, le=500)):
    return listar_eventos(limite)


@app.get("/sensores/status")
def sensores_status():
    return monitor_ir.status()


@app.get("/rfid/status")
def rfid_status():
    return monitor_rfid.status()


@app.get("/cancela/status")
def cancela_status():
    return obter_estado()


@app.post("/cancela/abrir")
def abrir():
    return comandar_cancela("abrir", origem="dashboard")


@app.post("/cancela/fechar")
def fechar():
    return comandar_cancela("fechar", origem="dashboard")


@app.post("/simulacao/obstaculo")
def obstaculo(
    presente: bool | None = Query(default=None),
    corpo: dict | None = Body(default=None),
):
    # Compatível com chamada query (?presente=true) ou JSON ({"presente": true}).
    if presente is None:
        if not isinstance(corpo, dict) or not isinstance(corpo.get("presente"), bool):
            return {"sucesso": False, "mensagem": "Informe 'presente' como booleano"}
        presente = corpo["presente"]
    return definir_obstaculo(presente)
