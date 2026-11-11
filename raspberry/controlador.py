"""Cancela SG90: manual V2 + temporizador RFID para protótipo supervisionado.

Atenção: VAGA_AUTO_SEM_SENSOR_BANCADA é EXCLUSIVO para ensaios de bancada,
sem veículos, pessoas ou objetos na trajetória da haste. Não usar em portões
reais. Com sensor ausente, NÃO existe proteção contra colisão ou esmagamento.

O modo RFID sem sensor exige AMBAS as variáveis:
  VAGA_FECHAMENTO_TESTE=1
  VAGA_AUTO_SEM_SENSOR_BANCADA=1
E expira 15 minutos após o start da API (reinicie só para novo ensaio supervisionado).
"""

import logging
import os
import time
from datetime import datetime
from threading import Event, RLock, Thread

from banco import conectar, inicializar_banco
from servo_cancela import inicializar_servo, abrir_servo, fechar_servo
from sensor_ultrassonico import obter_estado as obter_estado_ultrassom

log = logging.getLogger("controlador")
MODO_SIMULACAO = False
FECHAMENTO_MANUAL_TESTE = os.environ.get("VAGA_FECHAMENTO_TESTE", "0") == "1"
AUTO_SEM_SENSOR_BANCADA = os.environ.get("VAGA_AUTO_SEM_SENSOR_BANCADA", "0") == "1"
ATRASO_RFID_SEGUNDOS = 10.0
LIMITE_SESSAO_BANCADA_SEGUNDOS = 15 * 60
_INICIO_SESSAO = time.monotonic()

_lock = RLock()
# Posição apenas COMANDADA (não há feedback físico do SG90).
_ultima_posicao_comandada = None
_auto_cancelamento = None
_auto_horario_limite = None
_auto_estado = "inativo"


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _auto_permitido():
    return (
        FECHAMENTO_MANUAL_TESTE
        and AUTO_SEM_SENSOR_BANCADA
        and (time.monotonic() - _INICIO_SESSAO) < LIMITE_SESSAO_BANCADA_SEGUNDOS
    )


def inicializar_controle():
    inicializar_banco()
    with conectar() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS controle_cancela (
                id INTEGER PRIMARY KEY,
                aberta INTEGER NOT NULL DEFAULT 0,
                obstaculo INTEGER NOT NULL DEFAULT 0,
                atualizado TEXT NOT NULL
            )
        """)
        db.execute("""
            INSERT OR IGNORE INTO controle_cancela
            (id, aberta, obstaculo, atualizado) VALUES (1, 0, 0, ?)
        """, (agora(),))


def _sensor():
    try:
        return obter_estado_ultrassom()
    except Exception:
        log.exception("Erro ao consultar HC-SR04")
        return {"funcionando": False, "obstaculo": None, "distancia_cm": None}


def obter_estado():
    with conectar() as db:
        linha = db.execute("""
            SELECT aberta, obstaculo, atualizado
            FROM controle_cancela WHERE id=1
        """).fetchone()
    if linha is None:
        raise RuntimeError("Controle não inicializado")
    with _lock:
        posicao = _ultima_posicao_comandada
        agendado = _auto_cancelamento is not None
        restante = (round(max(0, _auto_horario_limite - time.monotonic()), 1)
                    if agendado and _auto_horario_limite is not None else None)
        estado_auto = _auto_estado
    return {
        "cancela_aberta": bool(linha["aberta"]) if posicao is None else posicao,
        "obstaculo": bool(linha["obstaculo"]),
        "obstaculo_simulado": bool(linha["obstaculo"]),
        "sensor_ultrassonico": _sensor(),
        "fechamento_habilitado": FECHAMENTO_MANUAL_TESTE,
        "fechamento_manual_teste": FECHAMENTO_MANUAL_TESTE,
        "seguranca_hc_sr04_validada": False,
        "fechamento_automatico_rfid": {
            "habilitado": _auto_permitido(),
            "modo_bancada_sem_sensor": AUTO_SEM_SENSOR_BANCADA,
            "agendado": agendado,
            "segundos_restantes": restante,
            "estado": estado_auto,
        },
        "posicao_confirmada_nesta_execucao": False,
        "comando_executado_nesta_execucao": posicao is not None,
        "atualizado": linha["atualizado"],
        "simulacao": MODO_SIMULACAO,
    }


def registrar(db, descricao):
    db.execute(
        "INSERT INTO eventos (horario, tipo, descricao) VALUES (?, ?, ?)",
        (agora(), "CANCELA", descricao),
    )


def _registrar_evento_tentativa(descricao):
    try:
        with conectar() as db:
            registrar(db, descricao)
    except Exception:
        log.exception("Erro ao registrar evento: %s", descricao)


def _cancelar_auto(motivo="cancelado"):
    global _auto_cancelamento, _auto_horario_limite, _auto_estado
    if _auto_cancelamento is not None:
        _auto_cancelamento.set()
        _auto_cancelamento = None
        _auto_horario_limite = None
        _auto_estado = motivo


def comandar_cancela(acao, origem="dashboard", automatico=False):
    """Preserva comandos manuais V2. Fechamento sem sensor só em bancada."""
    global _ultima_posicao_comandada

    if acao not in ("abrir", "fechar"):
        return {"sucesso": False, "mensagem": "Comando inválido"}

    with _lock:
        if automatico:
            if acao != "fechar" or not _auto_permitido():
                return {"sucesso": False, "mensagem": "Modo automático de bancada não habilitado ou expirado"}
        elif not origem.startswith("RFID UID "):
            # Comando manual prevalece e cancela fechamento pendente do RFID.
            _cancelar_auto("cancelado_pelo_dashboard")

        if acao == "fechar":
            if not FECHAMENTO_MANUAL_TESTE:
                return {"sucesso": False, "mensagem": "Ative o modo de teste para fechar fisicamente"}
            try:
                with conectar() as db:
                    linha = db.execute(
                        "SELECT obstaculo FROM controle_cancela WHERE id=1"
                    ).fetchone()
                # Trata o botão simulado como bloqueio adicional de bancada.
                # Ausência de obstáculo simulado NÃO equivale a passagem segura.
                if linha is None or bool(linha["obstaculo"]):
                    return {
                        "sucesso": False,
                        "mensagem": "Obstáculo SIMULADO ativo: fechamento bloqueado",
                    }
            except Exception:
                log.exception("Falha ao consultar estado simulado")
                return {"sucesso": False, "mensagem": "Erro ao consultar estado; fechamento bloqueado"}

        destino_aberto = acao == "abrir"
        # Para fechamento MANUAL, permitir repetir o pulso: não há sensor de posição
        # para comprovar que o servo terminou um movimento anterior.
        if _ultima_posicao_comandada is destino_aberto and (
            automatico or acao == "abrir"
        ):
            return {
                "sucesso": True,
                "mensagem": "Cancela já recebeu esse comando nesta execução",
            }

        try:
            inicializar_servo()
            if destino_aberto:
                abrir_servo()
            else:
                # Não utilizar com veículos ou pessoas na trajetória.
                fechar_servo()
        except Exception:
            log.exception("Erro ao acionar SG90: %s", acao)
            _registrar_evento_tentativa(f"Falha ao {acao} SG90 ({origem})")
            return {"sucesso": False, "mensagem": f"Falha ao {acao}; verifique logs da API"}

        _ultima_posicao_comandada = destino_aberto
        try:
            with conectar() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("""
                    UPDATE controle_cancela SET aberta=?, atualizado=? WHERE id=1
                """, (int(destino_aberto), agora()))
                registrar(db, f"SG90 comando {acao} ({origem}); PROTÓTIPO SEM SENSOR REAL")
        except Exception:
            log.exception("Servo acionado, falha ao registrar posição comandada")
            return {
                "sucesso": True,
                "mensagem": f"Comando {acao} enviado, mas falhou registro no SQLite",
            }

        return {
            "sucesso": True,
            "mensagem": (
                "Comando de ABRIR enviado ao SG90 (850 µs)."
                if destino_aberto else
                "Comando de FECHAR enviado ao SG90 (1550 µs, teste sem sensor)."
            ),
        }


def agendar_fechamento_rfid():
    """Agenda fechamento 10 s depois da ABERTURA RFID, somente no teste de bancada."""
    global _auto_cancelamento, _auto_horario_limite, _auto_estado
    with _lock:
        if _ultima_posicao_comandada is not True or not _auto_permitido():
            _auto_estado = "desabilitado_ou_sessao_expirada"
            return False
        _cancelar_auto("reagendado")
        cancelamento = Event()
        _auto_cancelamento = cancelamento
        _auto_horario_limite = time.monotonic() + ATRASO_RFID_SEGUNDOS
        _auto_estado = "contagem_10_segundos"
        Thread(
            target=_executar_fechamento_rfid,
            args=(cancelamento,),
            name="fechamento-rfid-bancada",
            daemon=True,
        ).start()
        return True


def _executar_fechamento_rfid(cancelamento):
    global _auto_cancelamento, _auto_horario_limite, _auto_estado
    if cancelamento.wait(ATRASO_RFID_SEGUNDOS):
        return
    with _lock:
        if cancelamento.is_set() or cancelamento is not _auto_cancelamento:
            return
        if not _auto_permitido():
            _auto_estado = "desabilitado_ou_sessao_expirada"
            _registrar_evento_tentativa("RFID: fechamento sem HC-SR04 bloqueado; modo expirado")
        elif _ultima_posicao_comandada is not True:
            _auto_estado = "cancelado_posicao_alterada"
        else:
            resultado = comandar_cancela(
                "fechar", origem="RFID apos 10s (bancada)", automatico=True
            )
            _auto_estado = "fechado_teste_bancada" if resultado.get("sucesso") else "bloqueado"
            if not resultado.get("sucesso"):
                _registrar_evento_tentativa(
                    "RFID: fechamento 10s não executado: " + resultado.get("mensagem", "")
                )
        if cancelamento is _auto_cancelamento:
            _auto_cancelamento = None
            _auto_horario_limite = None


def definir_obstaculo(presente):
    """Apenas simulado no dashboard; NÃO é medição do HC-SR04."""
    with conectar() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""
            UPDATE controle_cancela SET obstaculo=?, atualizado=? WHERE id=1
        """, (int(presente), agora()))
        registrar(
            db,
            "Obstáculo SIMULADO ativado" if presente
            else "Obstáculo SIMULADO desativado",
        )
    return obter_estado()
