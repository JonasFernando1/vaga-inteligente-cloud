
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from controlador import (
    inicializar_controle,
    obter_estado,
    comandar_cancela,
    definir_obstaculo
)
from sensores_ir import monitor_ir
from leitor_rfid import monitor_rfid


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_controle()

    monitor_ir.iniciar()

    try:
        monitor_rfid.iniciar()
    except Exception:
        monitor_ir.encerrar()
        raise

    try:
        yield
    finally:
        monitor_rfid.encerrar()
        monitor_ir.encerrar()


app = FastAPI(
    title="API Vaga Inteligente",
    version="1.2.0",
    lifespan=lifespan
)


class Obstaculo(BaseModel):
    presente: bool


@app.get("/")
def inicio():
    return {
        "projeto": "Vaga Inteligente",
        "status": "online",
        "vagas": "sensores_fisicos",
        "rfid": "leitor_fisico",
        "cancela": "simulacao"
    }


@app.get("/status")
def status():
    return obter_estado()


@app.get("/sensores/status")
def sensores_status():
    return monitor_ir.status()


@app.get("/rfid/status")
def rfid_status():
    return monitor_rfid.status()


@app.post("/cancela/abrir")
def abrir():
    return comandar_cancela("abrir")


@app.post("/cancela/fechar")
def fechar():
    return comandar_cancela("fechar")


@app.post("/simulacao/obstaculo")
def obstaculo(dados: Obstaculo):
    return definir_obstaculo(dados.presente)

