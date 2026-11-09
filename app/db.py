"""Banco: SQLite + FTS5. Guarda edições, páginas, resumos e a fila de jobs."""
import json
import sqlite3
from datetime import datetime, timezone

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS edicoes (
    id           INTEGER PRIMARY KEY,
    numero       INTEGER UNIQUE NOT NULL,
    data_pub     TEXT,
    titulo       TEXT,
    url_pdf      TEXT,
    paginas      INTEGER,
    chars        INTEGER,
    paginas_ocr  TEXT,
    status       TEXT DEFAULT 'nova',   -- nova|extraida|resumindo|resumida|erro
    erro         TEXT,
    criado_em    TEXT,
    atualizado_em TEXT
);

CREATE TABLE IF NOT EXISTS paginas (
    edicao_id INTEGER NOT NULL,
    n         INTEGER NOT NULL,
    texto     TEXT,
    ocr       INTEGER DEFAULT 0,
    PRIMARY KEY (edicao_id, n)
);

CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(
    texto,
    numero UNINDEXED,
    pagina UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS resumos (
    edicao_id INTEGER PRIMARY KEY,
    numero    INTEGER,
    modelo    TEXT,
    json      TEXT,
    criado_em TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT NOT NULL,      -- coletar | extrair | resumir
    edicao_id    INTEGER,
    prioridade   INTEGER DEFAULT 5,  -- menor roda antes
    estado       TEXT DEFAULT 'pendente',
    tentativas   INTEGER DEFAULT 0,
    erro         TEXT,
    criado_em    TEXT,
    atualizado_em TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado, prioridade, id);
"""


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def conectar() -> sqlite3.Connection:
    config.preparar_pastas()
    c = sqlite3.connect(config.DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init():
    with conectar() as c:
        c.executescript(ESQUEMA)
        # se o app foi fechado no meio de um job, ele volta para a fila
        c.execute("UPDATE jobs SET estado='pendente' WHERE estado='rodando'")
        c.execute("UPDATE edicoes SET status='extraida' WHERE status='resumindo'")


# ---------- edições ----------

def ja_existe(numero: int) -> bool:
    with conectar() as c:
        return c.execute("SELECT 1 FROM edicoes WHERE numero=?", (numero,)).fetchone() is not None


def salvar_edicao(dados: dict):
    campos = ("id", "numero", "data_pub", "titulo", "url_pdf", "paginas", "chars",
              "paginas_ocr", "status", "erro")
    vals = [json.dumps(dados[c]) if c == "paginas_ocr" else dados.get(c) for c in campos]
    with conectar() as c:
        c.execute(f"""INSERT INTO edicoes ({','.join(campos)}, criado_em, atualizado_em)
                      VALUES ({','.join('?'*len(campos))}, ?, ?)
                      ON CONFLICT(numero) DO UPDATE SET
                        status=excluded.status, paginas=excluded.paginas, chars=excluded.chars,
                        paginas_ocr=excluded.paginas_ocr, erro=excluded.erro,
                        atualizado_em=excluded.atualizado_em""",
                  (*vals, agora(), agora()))


def atualizar_status(numero: int, status: str, erro: str | None = None):
    with conectar() as c:
        c.execute("UPDATE edicoes SET status=?, erro=?, atualizado_em=? WHERE numero=?",
                  (status, erro, agora(), numero))


def edicao(numero: int):
    with conectar() as c:
        return c.execute("SELECT * FROM edicoes WHERE numero=?", (numero,)).fetchone()


def edicao_por_id(edicao_id: int):
    with conectar() as c:
        return c.execute("SELECT * FROM edicoes WHERE id=?", (edicao_id,)).fetchone()


def edicoes(pagina: int = 1, por_pagina: int = 20, somente_com_resumo=False):
    off = (pagina - 1) * por_pagina
    where = "WHERE 1=1" + ("" if not somente_com_resumo else " AND e.status IN ('resumida','resumindo')")
    with conectar() as c:
        total = c.execute(f"SELECT COUNT(*) FROM edicoes e {where}").fetchone()[0]
        linhas = c.execute(f"""
            SELECT e.*, r.json AS resumo_json
            FROM edicoes e LEFT JOIN resumos r ON r.edicao_id = e.id
            {where} ORDER BY e.numero DESC LIMIT ? OFFSET ?""",
            (por_pagina, off)).fetchall()
    return linhas, total


def numeros_recentes(quantidade: int) -> list[int]:
    with conectar() as c:
        return [r[0] for r in c.execute(
            "SELECT numero FROM edicoes ORDER BY numero DESC LIMIT ?", (quantidade,))]


def ultima_edicao() -> int:
    with conectar() as c:
        r = c.execute("SELECT MAX(numero) m FROM edicoes").fetchone()
        return r["m"] or 0


# ---------- páginas e busca ----------

def salvar_paginas(edicao_id: int, numero: int, paginas: list[str], ocr: list[int]):
    with conectar() as c:
        c.execute("DELETE FROM paginas WHERE edicao_id=?", (edicao_id,))
        c.execute("DELETE FROM busca WHERE numero=?", (numero,))
        for i, txt in enumerate(paginas, 1):
            c.execute("INSERT INTO paginas (edicao_id, n, texto, ocr) VALUES (?,?,?,?)",
                      (edicao_id, i, txt, 1 if i in ocr else 0))
            c.execute("INSERT INTO busca (texto, numero, pagina) VALUES (?,?,?)",
                      (txt, numero, i))


def paginas_de(edicao_id: int):
    with conectar() as c:
        return c.execute("SELECT * FROM paginas WHERE edicao_id=? ORDER BY n", (edicao_id,)).fetchall()


def buscar(termo: str, limite: int = 40):
    termo = termo.strip()
    if not termo:
        return []
    # cada palavra vira prefixo: "licitaç" acha "licitação"
    fts = " ".join(f'"{p.replace(chr(34), "")}"*' for p in termo.split() if p)
    with conectar() as c:
        try:
            return c.execute("""
                SELECT numero, pagina,
                       snippet(busca, 0, '<mark>', '</mark>', '…', 26) AS trecho,
                       bm25(busca) AS score
                FROM busca WHERE busca MATCH ? ORDER BY score LIMIT ?""",
                (fts, limite)).fetchall()
        except sqlite3.OperationalError:
            return []


# ---------- resumos ----------

def salvar_resumo(edicao_id: int, numero: int, modelo: str, obj: dict):
    with conectar() as c:
        c.execute("""INSERT INTO resumos (edicao_id, numero, modelo, json, criado_em)
                     VALUES (?,?,?,?,?)
                     ON CONFLICT(edicao_id) DO UPDATE SET json=excluded.json,
                       modelo=excluded.modelo, criado_em=excluded.criado_em""",
                  (edicao_id, numero, modelo, json.dumps(obj, ensure_ascii=False), agora()))


def resumo(numero: int):
    with conectar() as c:
        r = c.execute("SELECT * FROM resumos WHERE numero=?", (numero,)).fetchone()
        return json.loads(r["json"]) if r else None


# ---------- fila ----------

def enfileirar(tipo: str, edicao_id=None, prioridade: int = 5, dedupe=True):
    with conectar() as c:
        if dedupe:
            existe = c.execute(
                "SELECT 1 FROM jobs WHERE tipo=? AND edicao_id IS ? AND estado IN ('pendente','rodando')",
                (tipo, edicao_id)).fetchone()
            if existe:
                return None
        cur = c.execute("""INSERT INTO jobs (tipo, edicao_id, prioridade, estado, criado_em)
                           VALUES (?,?,?,'pendente',?)""",
                        (tipo, edicao_id, prioridade, agora()))
        return cur.lastrowid


def proximo_job():
    with conectar() as c:
        j = c.execute("""SELECT * FROM jobs WHERE estado='pendente'
                         ORDER BY prioridade, id LIMIT 1""").fetchone()
        if not j:
            return None
        c.execute("UPDATE jobs SET estado='rodando', atualizado_em=? WHERE id=?", (agora(), j["id"]))
    return j


def concluir_job(job_id: int, erro: str | None = None):
    with conectar() as c:
        j = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if erro and (j["tentativas"] or 0) < 3:
            c.execute("""UPDATE jobs SET estado='pendente', tentativas=tentativas+1,
                         erro=?, atualizado_em=? WHERE id=?""", (erro, agora(), job_id))
        else:
            c.execute("UPDATE jobs SET estado=?, erro=?, atualizado_em=? WHERE id=?",
                      ("erro" if erro else "feito", erro, agora(), job_id))


def fila_resumo():
    with conectar() as c:
        return c.execute("SELECT * FROM jobs WHERE estado IN ('pendente','rodando') ORDER BY id").fetchall()


def estatisticas():
    with conectar() as c:
        q = lambda s: c.execute(s).fetchone()[0]
        return {
            "edicoes": q("SELECT COUNT(*) FROM edicoes"),
            "resumidas": q("SELECT COUNT(*) FROM resumos"),
            "paginas": q("SELECT COUNT(*) FROM paginas"),
            "pendentes": q("SELECT COUNT(*) FROM jobs WHERE estado='pendente'"),
            "erros": q("SELECT COUNT(*) FROM jobs WHERE estado='erro'"),
        }
