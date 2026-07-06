"""Histórico de execuções, sessões e conhecimento aprendido — SQLite + SQLAlchemy."""

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.orm import declarative_base

logger = logging.getLogger(__name__)
Base = declarative_base()

# Política de refresh: um tópico/URL conta como "já estudado" só se foi estudado
# nos últimos RELEARN_DAYS dias. Depois disso, pode ser re-estudado (mantém o
# conhecimento atual sem voltar a duplicar — ChromaDB faz upsert por tópico e o
# dashboard mostra só o mais recente). 0 = nunca re-estuda.
RELEARN_DAYS = int(os.getenv("RELEARN_DAYS", 21))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value) -> datetime | None:
    """Parse tolerante de ISO datetime (usado ao importar backup)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


# ── Models ────────────────────────────────────────────────────

class Execution(Base):
    __tablename__ = "executions"
    id        = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=_now)
    request   = Column(Text, nullable=False)
    result    = Column(Text)
    status    = Column(String(20), default="pending")
    deleted   = Column(Boolean, default=False)


class SessionMessage(Base):
    __tablename__ = "session_messages"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), nullable=False, index=True)
    role       = Column(String(20), nullable=False)
    content    = Column(Text, nullable=False)
    timestamp  = Column(DateTime, default=_now)


class SessionMeta(Base):
    """Metadados de sessão — título gerado pelo LLM."""
    __tablename__ = "session_meta"
    session_id = Column(String(36), primary_key=True)
    title      = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)


class Notification(Base):
    """Aviso do A.P.O.L.O. sobre o que ele fez sozinho — torna a autonomia visível."""
    __tablename__ = "notifications"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    kind       = Column(String(30), default="info")   # study | gap | synthesis | info
    message    = Column(Text, nullable=False)
    link       = Column(Text)                          # opcional (ex.: url do estudo)
    read       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class ScheduledStudy(Base):
    """Estudo agendado — o A.P.O.L.O. estuda um tópico todo dia no horário definido."""
    __tablename__ = "scheduled_studies"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    topic      = Column(Text, nullable=False)
    time_of_day = Column(String(5), nullable=False)   # "HH:MM" (hora local)
    enabled    = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_now)
    last_run   = Column(DateTime)                      # quando rodou pela última vez


class LearnedTopic(Base):
    """Registro persistente do que o Apolo estudou autonomamente."""
    __tablename__ = "learned_topics"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    topic      = Column(Text, nullable=False)
    url        = Column(Text)
    summary    = Column(Text)          # síntese gerada pelo LLM
    category   = Column(String(50), default="web")
    studied_at = Column(DateTime, default=_now)


class Reaction(Base):
    """Feedback do usuário sobre respostas (👍/👎) — alimenta métricas de qualidade."""
    __tablename__ = "reactions"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    message_hash = Column(String(32), index=True, nullable=False)
    reaction     = Column(String(4), nullable=False)   # "up" ou "down"
    session_id   = Column(String(36))
    sources      = Column(Text, default="[]")           # JSON: URLs citadas
    created_at   = Column(DateTime, default=_now)


class CoderTask(Base):
    """Diário de bordo do Coder — cada tarefa executada vira um registro
    (autonomia visível + matéria-prima para automelhoria)."""
    __tablename__ = "coder_tasks"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=_now)
    task       = Column(Text, nullable=False)
    model      = Column(String(80))
    steps      = Column(Integer, default=0)      # passos ReAct usados
    wrote      = Column(Boolean, default=False)  # escreveu/editou arquivos?
    ran        = Column(Boolean, default=False)  # rodou comandos?
    reverted   = Column(Boolean, default=False)  # guarda de regressão desfez tudo?
    duration_s = Column(Float, default=0.0)
    summary    = Column(Text, default="")        # resumo final (truncado)


class BenchmarkRun(Base):
    """Histórico persistente de runs do benchmark de qualidade."""
    __tablename__ = "benchmark_runs"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    ran_at       = Column(DateTime, default=_now)
    model        = Column(String(80))
    avg_score    = Column(Float)
    avg_latency_ms = Column(Integer)
    total_ms     = Column(Integer)
    questions    = Column(Integer)
    results_json = Column(Text)   # JSON com detalhes por pergunta

