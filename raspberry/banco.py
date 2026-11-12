
import os
import sqlite3
from pathlib import Path
from datetime import datetime

CAMINHO_BANCO = Path(os.environ.get("VAGA_DB_PATH", Path(__file__).parent / "dados" / "estacionamento.db"))
CAMINHO_BANCO.parent.mkdir(exist_ok=True)


def conectar():
    conexao = sqlite3.connect(
        CAMINHO_BANCO,
        timeout=10
    )
    conexao.row_factory = sqlite3.Row
    conexao.execute("PRAGMA busy_timeout = 10000")
    return conexao


def agora():
    return datetime.now().astimezone().isoformat(
        timespec="seconds"
    )


def inicializar_banco():
    with conectar() as db:
        db.execute("PRAGMA journal_mode=WAL")

        db.executescript("""
        CREATE TABLE IF NOT EXISTS vagas (
            id INTEGER PRIMARY KEY,
            ocupada INTEGER NOT NULL DEFAULT 0,
            entrada TEXT
        );

        CREATE TABLE IF NOT EXISTS permanencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vaga_id INTEGER NOT NULL,
            entrada TEXT NOT NULL,
            saida TEXT,
            duracao_segundos INTEGER,
            FOREIGN KEY (vaga_id) REFERENCES vagas(id)
        );

        CREATE TABLE IF NOT EXISTS cartoes_rfid (
            uid TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            autorizado INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS eventos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            horario TEXT NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT NOT NULL
        );
        """)

        db.executemany(
            "INSERT OR IGNORE INTO vagas(id) VALUES (?)",
            [(1,), (2,)]
        )


def registrar_evento(tipo, descricao):
    with conectar() as db:
        db.execute(
            """INSERT INTO eventos
               (horario, tipo, descricao)
               VALUES (?, ?, ?)""",
            (agora(), tipo, descricao)
        )


def atualizar_vaga(vaga_id, ocupada):
    if vaga_id not in (1, 2):
        raise ValueError("Vaga inválida")

    with conectar() as db:
        # Garante atualização atômica
        db.execute("BEGIN IMMEDIATE")

        vaga = db.execute(
            "SELECT * FROM vagas WHERE id = ?",
            (vaga_id,)
        ).fetchone()

        if bool(vaga["ocupada"]) == ocupada:
            return False

        horario = agora()

        if ocupada:
            db.execute(
                """UPDATE vagas
                   SET ocupada = 1, entrada = ?
                   WHERE id = ?""",
                (horario, vaga_id)
            )

            db.execute(
                """INSERT INTO permanencias
                   (vaga_id, entrada)
                   VALUES (?, ?)""",
                (vaga_id, horario)
            )

            descricao = f"Entrada na vaga {vaga_id}"

        else:
            entrada = vaga["entrada"]

            if entrada:
                segundos = max(
                    0,
                    int((
                        datetime.fromisoformat(horario)
                        - datetime.fromisoformat(entrada)
                    ).total_seconds())
                )

                db.execute(
                    """UPDATE permanencias
                       SET saida = ?, duracao_segundos = ?
                       WHERE id = (
                           SELECT id FROM permanencias
                           WHERE vaga_id = ? AND saida IS NULL
                           ORDER BY id DESC LIMIT 1
                       )""",
                    (horario, segundos, vaga_id)
                )

            db.execute(
                """UPDATE vagas
                   SET ocupada = 0, entrada = NULL
                   WHERE id = ?""",
                (vaga_id,)
            )

            descricao = f"Saída da vaga {vaga_id}"

        db.execute(
            """INSERT INTO eventos
               (horario, tipo, descricao)
               VALUES (?, ?, ?)""",
            (horario, "VAGA", descricao)
        )

        return True


def listar_vagas():
    with conectar() as db:
        return [
            dict(linha) for linha in db.execute(
                "SELECT * FROM vagas ORDER BY id"
            ).fetchall()
        ]


def listar_permanencias():
    with conectar() as db:
        return [
            dict(linha) for linha in db.execute(
                """SELECT * FROM permanencias
                   ORDER BY id DESC LIMIT 100"""
            ).fetchall()
        ]


def listar_eventos():
    with conectar() as db:
        return [
            dict(linha) for linha in db.execute(
                """SELECT * FROM eventos
                   ORDER BY id DESC LIMIT 30"""
            ).fetchall()
        ]


def cadastrar_cartao(uid, nome, autorizado=True):
    with conectar() as db:
        db.execute(
            """INSERT INTO cartoes_rfid
               (uid, nome, autorizado)
               VALUES (?, ?, ?)
               ON CONFLICT(uid) DO UPDATE SET
                   nome = excluded.nome,
                   autorizado = excluded.autorizado""",
            (uid, nome, int(autorizado))
        )


def verificar_cartao(uid):
    with conectar() as db:
        cartao = db.execute(
            """SELECT nome, autorizado
               FROM cartoes_rfid WHERE uid = ?""",
            (uid,)
        ).fetchone()

        return bool(cartao and cartao["autorizado"])


