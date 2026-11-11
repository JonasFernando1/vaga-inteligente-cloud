"""Banco SQLite local da Vaga Inteligente.

Compatível com os nomes usados nas versões anteriores, sem apagar dados.
"""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Lock
import os
import sqlite3

BASE = Path(__file__).resolve().parent
CAMINHO_BANCO = Path(os.environ.get("VAGA_DB_PATH", str(BASE / "dados" / "estacionamento.db")))
_INIT_LOCK = Lock()


def agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def conectar():
    CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(CAMINHO_BANCO), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def inicializar_banco():
    with _INIT_LOCK:
        with conectar() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS vagas (
                    id INTEGER PRIMARY KEY,
                    ocupada INTEGER NOT NULL DEFAULT 0,
                    entrada TEXT
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS permanencias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    vaga_id INTEGER NOT NULL,
                    entrada TEXT NOT NULL,
                    saida TEXT NOT NULL,
                    duracao_segundos INTEGER NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS cartoes_rfid (
                    uid TEXT PRIMARY KEY,
                    nome TEXT NOT NULL,
                    autorizado INTEGER NOT NULL DEFAULT 0
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS eventos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    horario TEXT NOT NULL,
                    tipo TEXT NOT NULL,
                    descricao TEXT NOT NULL
                )
            """)
            for vaga_id in (1, 2):
                db.execute(
                    "INSERT OR IGNORE INTO vagas (id, ocupada) VALUES (?, 0)",
                    (vaga_id,),
                )


def _duracao(entrada, saida):
    try:
        inicio = datetime.fromisoformat(entrada.replace("Z", "+00:00"))
        fim = datetime.fromisoformat(saida)
        if inicio.tzinfo is None:
            inicio = inicio.replace(tzinfo=fim.tzinfo)
        return max(0, int((fim - inicio).total_seconds()))
    except (ValueError, TypeError):
        return 0


def atualizar_vaga(vaga_id: int, ocupada: bool):
    """Salva somente transições; preserva histórico das permanências."""
    if vaga_id not in (1, 2):
        raise ValueError("Vaga inválida")
    instante = agora()
    with conectar() as db:
        db.execute("BEGIN IMMEDIATE")
        atual = db.execute(
            "SELECT ocupada, entrada FROM vagas WHERE id=?", (vaga_id,)
        ).fetchone()
        if atual is None:
            raise RuntimeError(f"Vaga {vaga_id} não cadastrada")
        anterior = bool(atual["ocupada"])
        if anterior == bool(ocupada):
            return False
        if ocupada:
            db.execute(
                "UPDATE vagas SET ocupada=1, entrada=? WHERE id=?",
                (instante, vaga_id),
            )
            evento = f"Vaga {vaga_id} ocupada"
        else:
            if atual["entrada"]:
                db.execute(
                    """INSERT INTO permanencias
                       (vaga_id, entrada, saida, duracao_segundos)
                       VALUES (?, ?, ?, ?)""",
                    (vaga_id, atual["entrada"], instante,
                     _duracao(atual["entrada"], instante)),
                )
            db.execute(
                "UPDATE vagas SET ocupada=0, entrada=NULL WHERE id=?", (vaga_id,)
            )
            evento = f"Vaga {vaga_id} liberada"
        db.execute(
            "INSERT INTO eventos (horario, tipo, descricao) VALUES (?, ?, ?)",
            (instante, "VAGA", evento),
        )
    return True


def listar_vagas():
    with conectar() as db:
        return [dict(linha) for linha in db.execute(
            "SELECT id, ocupada, entrada FROM vagas ORDER BY id"
        ).fetchall()]


def listar_permanencias(limite=50):
    with conectar() as db:
        return [dict(linha) for linha in db.execute(
            """SELECT id, vaga_id, entrada, saida, duracao_segundos
               FROM permanencias ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limite), 500)),),
        ).fetchall()]


def listar_eventos(limite=50):
    with conectar() as db:
        return [dict(linha) for linha in db.execute(
            "SELECT id, horario, tipo, descricao FROM eventos ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limite), 500)),),
        ).fetchall()]


def registrar_evento(tipo, descricao):
    with conectar() as db:
        db.execute(
            "INSERT INTO eventos (horario, tipo, descricao) VALUES (?, ?, ?)",
            (agora(), str(tipo), str(descricao)),
        )


def cadastrar_cartao(uid, nome, autorizado=True):
    with conectar() as db:
        db.execute("""
            INSERT INTO cartoes_rfid (uid, nome, autorizado) VALUES (?, ?, ?)
            ON CONFLICT(uid) DO UPDATE SET nome=excluded.nome,
                autorizado=excluded.autorizado
        """, (str(uid), str(nome), int(bool(autorizado))))


def verificar_cartao(uid):
    with conectar() as db:
        linha = db.execute(
            "SELECT uid, nome, autorizado FROM cartoes_rfid WHERE uid=?",
            (str(uid),),
        ).fetchone()
    return dict(linha) if linha else None
