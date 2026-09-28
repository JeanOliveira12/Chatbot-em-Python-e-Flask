"""
db.py — Camada de banco de dados (SQLite).

Guarda as conversas e as mensagens. Cada conversa tem um "status":
  - "bot":    o chatbot está respondendo
  - "humano": foi transferida; só um atendente responde (pelo painel)
  - "encerrada": finalizada no painel

Papéis de mensagem ("papel"):
  - "user":      o cliente
  - "assistant": o chatbot (IA)
  - "atendente": um humano respondendo pelo painel
  - "sistema":   avisos automáticos (ex.: "conversa transferida")
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "chatbot.db")


def conectar():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # permite acessar colunas pelo nome: linha["status"]
    return conn


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def iniciar_banco():
    """Cria as tabelas se ainda não existirem. Chamado ao iniciar o app."""
    with conectar() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                criada_em TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'bot',
                motivo_transferencia TEXT
            );
            CREATE TABLE IF NOT EXISTS mensagens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversa_id INTEGER NOT NULL REFERENCES conversas(id),
                papel TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                criada_em TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_msg_conversa ON mensagens(conversa_id);
            """
        )


def criar_conversa():
    with conectar() as conn:
        cur = conn.execute("INSERT INTO conversas (criada_em) VALUES (?)", (agora(),))
        return cur.lastrowid


def obter_conversa(conversa_id):
    with conectar() as conn:
        return conn.execute("SELECT * FROM conversas WHERE id = ?", (conversa_id,)).fetchone()


def atualizar_status(conversa_id, status, motivo=None):
    with conectar() as conn:
        conn.execute(
            "UPDATE conversas SET status = ?, motivo_transferencia = COALESCE(?, motivo_transferencia) WHERE id = ?",
            (status, motivo, conversa_id),
        )


def salvar_mensagem(conversa_id, papel, conteudo):
    with conectar() as conn:
        cur = conn.execute(
            "INSERT INTO mensagens (conversa_id, papel, conteudo, criada_em) VALUES (?, ?, ?, ?)",
            (conversa_id, papel, conteudo, agora()),
        )
        return cur.lastrowid


def mensagens_da_conversa(conversa_id, depois_de=0):
    """Retorna as mensagens em ordem. 'depois_de' permite buscar só as novas (polling)."""
    with conectar() as conn:
        linhas = conn.execute(
            "SELECT * FROM mensagens WHERE conversa_id = ? AND id > ? ORDER BY id",
            (conversa_id, depois_de),
        ).fetchall()
        return [dict(l) for l in linhas]


def listar_conversas():
    """Lista para o painel: conversas transferidas aparecem primeiro."""
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT c.*,
                   COUNT(m.id) AS total_mensagens,
                   MAX(m.criada_em) AS ultima_atividade,
                   (SELECT conteudo FROM mensagens WHERE conversa_id = c.id AND papel = 'user'
                     ORDER BY id LIMIT 1) AS primeira_pergunta
            FROM conversas c
            LEFT JOIN mensagens m ON m.conversa_id = c.id
            GROUP BY c.id
            ORDER BY (c.status = 'humano') DESC, ultima_atividade DESC
            """
        ).fetchall()
        return [dict(l) for l in linhas]
