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
    kind       = Column(String(30), default="info")   # study | gap | synthesis | info | reminder | briefing
    message    = Column(Text, nullable=False)
    link       = Column(Text)                          # opcional (ex.: url do estudo)
    read       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    # Relevância (M4 4.3): prioridade (0=ruído de fundo … 3=importante) e contagem
    # de eventos colapsados (avisos de baixa prioridade viram 1 só, com count).
    priority   = Column(Integer, default=1)
    count      = Column(Integer, default=1)


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


class ReviewSchedule(Base):
    """Repetição espaçada (M8, Épico 8.1): agenda de revisão SM-2 de cada tópico.
    O A.P.O.L.O. se auto-testa em intervalos crescentes; esquecer volta o tópico
    para a fila. `topic` é a chave (1 agenda por tópico)."""
    __tablename__ = "review_schedule"
    topic         = Column(Text, primary_key=True)
    ease          = Column(Float, default=2.5)
    interval      = Column(Integer, default=0)     # dias até a próxima revisão
    reps          = Column(Integer, default=0)     # acertos seguidos
    lapses        = Column(Integer, default=0)     # quantas vezes esqueceu
    due_at        = Column(DateTime, index=True, default=_now)
    last_reviewed = Column(DateTime)


class TopicEdge(Base):
    """Aresta do grafo de conhecimento (M8, Épico 8.3): dois tópicos ligados pelos
    conceitos que compartilham. Guardada em ordem canônica (a <= b), 1 por par."""
    __tablename__ = "topic_edges"
    a          = Column(Text, primary_key=True)
    b          = Column(Text, primary_key=True)
    weight     = Column(Float, default=0.0)     # força da conexão (Jaccard)
    shared     = Column(Text, default="")       # conceitos em comum (separados por ;)
    updated_at = Column(DateTime, default=_now)


class Reaction(Base):
    """Feedback do usuário sobre respostas (👍/👎) — alimenta métricas de qualidade.
    O 'por quê' (M9 9.2) + o par pergunta/resposta tornam um 👎 ACIONÁVEL: vira
    dado de melhoria e memória, não só um contador."""
    __tablename__ = "reactions"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    message_hash = Column(String(32), index=True, nullable=False)
    reaction     = Column(String(4), nullable=False)   # "up" ou "down"
    session_id   = Column(String(36))
    sources      = Column(Text, default="[]")           # JSON: URLs citadas
    reason       = Column(Text, default="")             # M9 9.2: por que (texto do Leo)
    question     = Column(Text, default="")             # pergunta que gerou a resposta
    answer       = Column(Text, default="")             # trecho da resposta avaliada
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


class EvalRun(Base):
    """Placar de um run do harness de avaliação (M9, Épico 9.1): a suíte canário
    (chat/coder/recall/trap) rodada num instante. `hallucination_rate` = fração das
    armadilhas que o modelo mordeu — o número que prova a queda de alucinação (M7)."""
    __tablename__ = "eval_runs"
    id                 = Column(Integer, primary_key=True, autoincrement=True)
    ran_at             = Column(DateTime, default=_now, index=True)
    suite              = Column(String(40), default="canary")
    score              = Column(Float)          # nota geral 0..1
    passed             = Column(Integer)        # tarefas aprovadas
    total              = Column(Integer)        # tarefas totais
    hallucination_rate = Column(Float, default=0.0)
    by_kind_json       = Column(Text, default="{}")
    results_json       = Column(Text, default="[]")


class Permission(Base):
    """Consentimento do usuário para uma capacidade de agência (M6, Épico 6.1).
    Nada que toque o mundo (ler arquivos, agenda, e-mail) roda sem um grant aqui."""
    __tablename__ = "permissions"
    scope      = Column(String(60), primary_key=True)   # ex.: files.read, calendar.read
    granted    = Column(Boolean, default=True)
    granted_at = Column(DateTime, default=_now)
    note       = Column(Text, default="")               # ex.: caminho autorizado


class ToolAudit(Base):
    """Log de auditoria de TODA invocação de ferramenta de agência (M6, Épico 6.1)
    — permitida ou negada. Torna a agência inspecionável e reversível."""
    __tablename__ = "tool_audit"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    tool       = Column(String(60), nullable=False)
    scope      = Column(String(60), default="")
    allowed    = Column(Boolean, default=False)
    args       = Column(Text, default="")               # resumo dos argumentos
    result     = Column(Text, default="")               # resumo do resultado
    created_at = Column(DateTime, default=_now, index=True)


class UndoLog(Base):
    """Trilha de ações REVERSÍVEIS (M10, Épico 10.1): cada ação que modificou o
    mundo (ex.: escrita de arquivo) grava aqui os dados para desfazê-la. É a
    trilha de auditoria reversível que o DoD do M10 exige."""
    __tablename__ = "undo_log"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    kind        = Column(String(40), nullable=False)   # tipo da ação (ex.: files.write)
    description = Column(Text, default="")             # frase humana ("Criou notas.md")
    undo_json   = Column(Text, default="{}")           # dados p/ reverter (JSON)
    created_at  = Column(DateTime, default=_now, index=True)
    undone      = Column(Boolean, default=False)
    undone_at   = Column(DateTime)


class Reminder(Base):
    """Lembrete/follow-up (M4, Épico 4.2): compromisso detectado numa conversa
    ('me lembra de X') ou criado à mão. O A.P.O.L.O. resurface no momento certo."""
    __tablename__ = "reminders"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    text       = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)
    due_at     = Column(DateTime, index=True)   # quando resurfacear (opcional)
    session_id = Column(String(36))             # conversa de origem
    done       = Column(Boolean, default=False)
    notified   = Column(Boolean, default=False)  # já avisado ao vencer?


class Episode(Base):
    """Memória episódica/autobiográfica (M2): cada conversa vira um episódio
    resumido e DATADO ('2026-07-06: fechamos o Épico 2.1'). Base do recall
    temporal — 'o que a gente fez ontem/semana passada?'."""
    __tablename__ = "episodes"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), index=True)   # sessão de origem (evita duplicar)
    occurred_at = Column(DateTime, default=_now, index=True)  # quando o episódio aconteceu
    title      = Column(Text, nullable=False)     # frase curta ("fechamos o Épico 2.1")
    summary    = Column(Text, default="")         # resumo mais longo do que rolou
    tags       = Column(Text, default="")         # JSON de tags
    created_at = Column(DateTime, default=_now)

