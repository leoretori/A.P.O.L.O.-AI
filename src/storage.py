"""Histórico de execuções, sessões e conhecimento aprendido — SQLite + SQLAlchemy."""

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.orm import declarative_base, Session

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


# ── Manager ───────────────────────────────────────────────────

class DatabaseManager:
    def __init__(self, database_url: str = "sqlite:///data/apolo.db"):
        self.engine = create_engine(database_url, echo=False)
        Base.metadata.create_all(self.engine)
        logger.debug(f"Banco conectado: {database_url}")

    # ── Execuções ─────────────────────────────────────────────
    def save_execution(self, data: dict) -> int:
        with Session(self.engine) as s:
            row = Execution(
                timestamp=datetime.fromisoformat(data.get("timestamp", _now().isoformat())),
                request=data["request"],
                result=data.get("result", ""),
                status=data.get("status", "pending"),
            )
            s.add(row); s.commit()
            return row.id

    def get_history(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(Execution)
                    .filter(Execution.deleted == False)
                    .order_by(Execution.timestamp.desc())
                    .limit(limit).all())
            return [{"id": r.id, "timestamp": r.timestamp.isoformat(),
                     "request": r.request, "status": r.status} for r in rows]

    def soft_delete(self, execution_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(Execution, execution_id)
            if row:
                row.deleted = True; s.commit(); return True
            return False

    # ── Sessões de conversa ───────────────────────────────────
    def save_message(self, session_id: str, role: str, content: str) -> None:
        with Session(self.engine) as s:
            s.add(SessionMessage(session_id=session_id, role=role, content=content))
            s.commit()

    def load_session(self, session_id: str) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.timestamp.asc()).all())
            return [{"role": r.role, "content": r.content} for r in rows]

    def delete_session(self, session_id: str) -> None:
        with Session(self.engine) as s:
            s.query(SessionMessage).filter(SessionMessage.session_id == session_id).delete()
            # Remove também o título — senão sobra metadado órfão (sessão fantasma).
            s.query(SessionMeta).filter(SessionMeta.session_id == session_id).delete()
            s.commit()

    def save_session_title(self, session_id: str, title: str) -> None:
        with Session(self.engine) as s:
            existing = s.get(SessionMeta, session_id)
            if existing:
                existing.title = title
            else:
                s.add(SessionMeta(session_id=session_id, title=title))
            s.commit()

    def list_sessions(self, days: int = 0, limit: int = 100) -> list[dict]:
        """Sessões recentes para a sidebar. days=0 → todo o histórico (chats antigos
        continuam aparecendo); >0 limita à janela. Ordena pela última atividade."""
        with Session(self.engine) as s:
            q = (s.query(SessionMessage)
                 .filter(SessionMessage.role == "user"))
            if days > 0:
                q = q.filter(SessionMessage.timestamp >= _now() - timedelta(days=days))
            rows = q.order_by(SessionMessage.timestamp.desc()).all()
            seen: dict[str, dict] = {}
            for r in rows:
                if r.session_id not in seen:
                    meta = s.get(SessionMeta, r.session_id)
                    seen[r.session_id] = {
                        "session_id": r.session_id,
                        "title": meta.title if meta else r.content[:60],
                        "first_message": r.content[:80],
                        "last_active": r.timestamp.isoformat(),
                    }
            return list(seen.values())[:limit]

    def search_messages(self, query: str, limit: int = 30) -> list[dict]:
        """Busca no histórico de conversas — retorna trechos com a sessão de origem.
        Agrupa por sessão (mostra o primeiro acerto de cada) para a sidebar de busca."""
        q = (query or "").strip()
        if len(q) < 2:
            return []
        like = f"%{q}%"
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.content.ilike(like))
                    .order_by(SessionMessage.timestamp.desc())
                    .limit(limit * 8).all())
            seen: dict[str, dict] = {}
            for r in rows:
                if r.session_id in seen:
                    continue
                meta = s.get(SessionMeta, r.session_id)
                # Recorta um trecho ao redor do termo encontrado.
                low = r.content.lower()
                idx = low.find(q.lower())
                start = max(0, idx - 40)
                snippet = ("…" if start > 0 else "") + r.content[start:start + 140].strip()
                seen[r.session_id] = {
                    "session_id": r.session_id,
                    "title": meta.title if meta else r.content[:60],
                    "role": r.role,
                    "snippet": snippet,
                    "matched_at": r.timestamp.isoformat(),
                }
                if len(seen) >= limit:
                    break
            return list(seen.values())

    def export_session_markdown(self, session_id: str) -> str:
        """Exporta uma conversa como Markdown legível (título + turnos)."""
        with Session(self.engine) as s:
            meta = s.get(SessionMeta, session_id)
            rows = (s.query(SessionMessage)
                    .filter(SessionMessage.session_id == session_id)
                    .order_by(SessionMessage.timestamp.asc()).all())
            title = meta.title if meta else "Conversa"
            out = [f"# {title}", ""]
            if rows:
                out.append(f"*Exportado de A.P.O.L.O. — {len(rows)} mensagens*")
                out.append("")
            for r in rows:
                who = "🧑 Você" if r.role == "user" else "☀️ A.P.O.L.O."
                ts = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else ""
                out.append(f"### {who}  \n<sub>{ts}</sub>")
                out.append("")
                out.append(r.content or "")
                out.append("")
                out.append("---")
                out.append("")
            return "\n".join(out).strip() + "\n"

    def export_all(self) -> dict:
        """Dump completo do SQLite (sessões + tópicos aprendidos) para backup/export."""
        with Session(self.engine) as s:
            messages = [
                {"session_id": r.session_id, "role": r.role, "content": r.content,
                 "timestamp": r.timestamp.isoformat() if r.timestamp else None}
                for r in s.query(SessionMessage).order_by(SessionMessage.timestamp.asc()).all()
            ]
            titles = [
                {"session_id": r.session_id, "title": r.title,
                 "created_at": r.created_at.isoformat() if r.created_at else None}
                for r in s.query(SessionMeta).all()
            ]
            topics = [
                {"topic": r.topic, "url": r.url, "summary": r.summary,
                 "category": r.category,
                 "studied_at": r.studied_at.isoformat() if r.studied_at else None}
                for r in s.query(LearnedTopic).order_by(LearnedTopic.studied_at.asc()).all()
            ]
        return {
            "exported_at": _now().isoformat(),
            "counts": {"messages": len(messages), "sessions": len(titles), "learned_topics": len(topics)},
            "sessions_titles": titles,
            "messages": messages,
            "learned_topics": topics,
        }

    # ── Notificações ──────────────────────────────────────────
    NOTIF_KEEP = 200  # notificações são efêmeras → mantém só as mais recentes

    def add_notification(self, message: str, kind: str = "info", link: str = "") -> dict:
        with Session(self.engine) as s:
            row = Notification(message=message[:500], kind=kind, link=link or None)
            s.add(row); s.commit()
            result = {"id": row.id, "kind": row.kind, "message": row.message,
                      "link": row.link, "read": False,
                      "created_at": row.created_at.isoformat()}
            # Poda: remove o excedente além das NOTIF_KEEP mais recentes.
            ids = [r.id for r in (s.query(Notification.id)
                                  .order_by(Notification.created_at.desc())
                                  .offset(self.NOTIF_KEEP).all())]
            if ids:
                (s.query(Notification).filter(Notification.id.in_(ids))
                 .delete(synchronize_session=False))
                s.commit()
            return result

    def list_notifications(self, limit: int = 30, unread_only: bool = False) -> list[dict]:
        with Session(self.engine) as s:
            q = s.query(Notification)
            if unread_only:
                q = q.filter(Notification.read == False)
            rows = q.order_by(Notification.created_at.desc()).limit(limit).all()
            return [{"id": r.id, "kind": r.kind, "message": r.message, "link": r.link,
                     "read": r.read, "created_at": r.created_at.isoformat()} for r in rows]

    def unread_count(self) -> int:
        with Session(self.engine) as s:
            return s.query(Notification).filter(Notification.read == False).count()

    def mark_notifications_read(self) -> int:
        with Session(self.engine) as s:
            n = (s.query(Notification).filter(Notification.read == False)
                 .update({Notification.read: True}, synchronize_session=False))
            s.commit()
            return n

    def clear_notifications(self) -> int:
        with Session(self.engine) as s:
            n = s.query(Notification).delete(synchronize_session=False)
            s.commit()
            return n

    # ── Estudos agendados ─────────────────────────────────────
    def add_schedule(self, topic: str, time_of_day: str) -> dict:
        with Session(self.engine) as s:
            row = ScheduledStudy(topic=topic.strip()[:200], time_of_day=time_of_day.strip())
            s.add(row); s.commit()
            return {"id": row.id, "topic": row.topic, "time_of_day": row.time_of_day,
                    "enabled": row.enabled, "last_run": None}

    def list_schedules(self) -> list[dict]:
        with Session(self.engine) as s:
            rows = s.query(ScheduledStudy).order_by(ScheduledStudy.time_of_day.asc()).all()
            return [{"id": r.id, "topic": r.topic, "time_of_day": r.time_of_day,
                     "enabled": r.enabled,
                     "last_run": r.last_run.isoformat() if r.last_run else None}
                    for r in rows]

    def delete_schedule(self, schedule_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if not row:
                return False
            s.delete(row); s.commit()
            return True

    def toggle_schedule(self, schedule_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if not row:
                return False
            row.enabled = not row.enabled
            s.commit()
            return True

    def due_schedules(self, now_local: datetime) -> list[dict]:
        """Agendamentos cujo horário 'HH:MM' já passou hoje e que ainda não rodaram hoje.
        Retorna os que devem disparar agora; o caller marca como executados."""
        hhmm = now_local.strftime("%H:%M")
        today = now_local.date()
        due: list[dict] = []
        with Session(self.engine) as s:
            rows = s.query(ScheduledStudy).filter(ScheduledStudy.enabled == True).all()
            for r in rows:
                if r.last_run and r.last_run.date() == today:
                    continue  # já rodou hoje
                if r.time_of_day <= hhmm:  # chegou (ou passou) a hora
                    due.append({"id": r.id, "topic": r.topic, "time_of_day": r.time_of_day})
        return due

    def mark_schedule_ran(self, schedule_id: int, when: datetime) -> None:
        with Session(self.engine) as s:
            row = s.get(ScheduledStudy, schedule_id)
            if row:
                row.last_run = when
                s.commit()

    def import_all(self, data: dict) -> dict:
        """Restaura um backup gerado por export_all(). Idempotente: pula mensagens e
        tópicos já presentes (mesmo conteúdo/url) e faz upsert de títulos."""
        added = {"messages": 0, "sessions": 0, "learned_topics": 0}
        with Session(self.engine) as s:
            # Títulos (upsert por session_id)
            for t in data.get("sessions_titles", []):
                sid = t.get("session_id")
                if not sid:
                    continue
                existing = s.get(SessionMeta, sid)
                if existing:
                    existing.title = t.get("title") or existing.title
                else:
                    s.add(SessionMeta(session_id=sid, title=t.get("title") or "(sem título)"))
                    added["sessions"] += 1

            # Mensagens — evita duplicar (mesma sessão+role+conteúdo+timestamp)
            for m in data.get("messages", []):
                sid, role, content = m.get("session_id"), m.get("role"), m.get("content")
                if not (sid and role and content is not None):
                    continue
                ts = _parse_dt(m.get("timestamp"))
                dup = (s.query(SessionMessage.id)
                       .filter(SessionMessage.session_id == sid,
                               SessionMessage.role == role,
                               SessionMessage.content == content).first())
                if dup:
                    continue
                row = SessionMessage(session_id=sid, role=role, content=content)
                if ts:
                    row.timestamp = ts
                s.add(row)
                added["messages"] += 1

            # Tópicos aprendidos — evita duplicar pela URL (ou topic se sem url)
            for lt in data.get("learned_topics", []):
                topic = lt.get("topic")
                if not topic:
                    continue
                url = lt.get("url") or ""
                q = s.query(LearnedTopic.id)
                q = q.filter(LearnedTopic.url == url) if url else q.filter(LearnedTopic.topic == topic)
                if q.first():
                    continue
                ts = _parse_dt(lt.get("studied_at"))
                row = LearnedTopic(topic=topic, url=url or None,
                                   summary=lt.get("summary"), category=lt.get("category") or "web")
                if ts:
                    row.studied_at = ts
                s.add(row)
                added["learned_topics"] += 1

            s.commit()
        return added

    def cleanup_orphan_meta(self) -> int:
        """Remove títulos de sessões que não têm mais mensagens (limpeza de fantasmas)."""
        with Session(self.engine) as s:
            metas = s.query(SessionMeta.session_id).all()
            removed = 0
            for (sid,) in metas:
                has_msg = (s.query(SessionMessage.id)
                           .filter(SessionMessage.session_id == sid).first())
                if not has_msg:
                    s.query(SessionMeta).filter(SessionMeta.session_id == sid).delete()
                    removed += 1
            if removed:
                s.commit()
        return removed

    # ── Tópicos aprendidos ────────────────────────────────────
    def save_learned_topic(self, topic: str, url: str, summary: str, category: str = "web") -> None:
        with Session(self.engine) as s:
            s.add(LearnedTopic(topic=topic, url=url, summary=summary, category=category))
            s.commit()

    def is_url_studied(self, url: str) -> bool:
        """Evita re-estudar a mesma URL — mas libera após RELEARN_DAYS (refresh)."""
        with Session(self.engine) as s:
            q = s.query(LearnedTopic).filter(LearnedTopic.url == url)
            if RELEARN_DAYS > 0:
                q = q.filter(LearnedTopic.studied_at >= _now() - timedelta(days=RELEARN_DAYS))
            return q.count() > 0

    def is_topic_studied(self, topic: str) -> bool:
        """Anti-duplicação na rotação dos agentes — mas libera após RELEARN_DAYS (refresh)."""
        if not topic:
            return False
        with Session(self.engine) as s:
            q = s.query(LearnedTopic).filter(LearnedTopic.topic == topic)
            if RELEARN_DAYS > 0:
                q = q.filter(LearnedTopic.studied_at >= _now() - timedelta(days=RELEARN_DAYS))
            return q.first() is not None

    def delete_learned_topic(self, topic_id: int) -> dict | None:
        """Remove um conhecimento (e todos os re-estudos do mesmo tópico) do log.
        Retorna {topic, url} para o caller propagar a remoção a Supabase/RAG."""
        with Session(self.engine) as s:
            row = s.get(LearnedTopic, topic_id)
            if not row:
                return None
            topic, url = row.topic, row.url
            (s.query(LearnedTopic).filter(LearnedTopic.topic == topic)
             .delete(synchronize_session=False))
            s.commit()
            return {"topic": topic, "url": url}

    def count_topic_duplicates(self) -> int:
        """Quantos registros são re-estudos do mesmo tópico (excedentes)."""
        with Session(self.engine) as s:
            total = s.query(LearnedTopic).count()
            from sqlalchemy import func, distinct
            uniq = s.query(func.count(distinct(LearnedTopic.topic))).scalar() or 0
        return max(0, total - uniq)

    def dedup_learned_topics(self) -> int:
        """Remove re-estudos repetidos do log, mantendo o registro mais recente de cada
        tópico. Retorna quantos foram removidos."""
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic.id, LearnedTopic.topic)
                    .order_by(LearnedTopic.studied_at.desc()).all())
            seen: set[str] = set()
            to_del: list[int] = []
            for rid, topic in rows:
                key = (topic or "").strip().lower()
                if key in seen:
                    to_del.append(rid)
                else:
                    seen.add(key)
            for i in range(0, len(to_del), 500):
                (s.query(LearnedTopic)
                 .filter(LearnedTopic.id.in_(to_del[i:i + 500]))
                 .delete(synchronize_session=False))
            if to_del:
                s.commit()
        return len(to_del)

    def get_learning_history(self, limit: int = 30) -> list[dict]:
        """Tópicos aprendidos, SEM repetir o mesmo tópico (mostra o mais recente de cada).
        Evita a sensação de 'repetindo muito' no dashboard."""
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic)
                    .order_by(LearnedTopic.studied_at.desc())
                    .limit(limit * 6).all())
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            key = (r.topic or "").strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"id": r.id, "topic": r.topic, "url": r.url,
                        "summary": r.summary, "category": r.category,
                        "studied_at": r.studied_at.isoformat()})
            if len(out) >= limit:
                break
        return out

    # ── Diário de tarefas do Coder ────────────────────────────
    def save_coder_task(self, task: str, model: str = "", steps: int = 0,
                        wrote: bool = False, ran: bool = False, reverted: bool = False,
                        duration_s: float = 0.0, summary: str = "") -> int:
        with Session(self.engine) as s:
            row = CoderTask(task=task[:500], model=model, steps=steps, wrote=wrote,
                            ran=ran, reverted=reverted, duration_s=round(duration_s, 1),
                            summary=(summary or "")[:400])
            s.add(row); s.commit()
            return row.id

    def get_coder_tasks(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(CoderTask)
                    .order_by(CoderTask.id.desc()).limit(limit).all())
            return [{"id": r.id, "created_at": r.created_at.isoformat(),
                     "task": r.task, "model": r.model, "steps": r.steps,
                     "wrote": r.wrote, "ran": r.ran, "reverted": r.reverted,
                     "duration_s": r.duration_s, "summary": r.summary} for r in rows]

    def get_coder_stats(self, window: int = 10) -> dict:
        """Taxa de sucesso do Coder + TENDÊNCIA: compara a janela recente com a
        anterior (medir → melhorar → provar — as lições estão funcionando?)."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            total = s.query(func.count(CoderTask.id)).scalar() or 0
            reverted = (s.query(func.count(CoderTask.id))
                        .filter(CoderTask.reverted == True).scalar() or 0)
            flags = [r.reverted for r in
                     s.query(CoderTask.reverted)
                      .order_by(CoderTask.id.desc()).limit(window * 2).all()]

        def _rate(fs: list) -> int | None:
            return round(100 * sum(1 for f in fs if not f) / len(fs)) if fs else None

        recent_rate = _rate(flags[:window])
        prev_rate = _rate(flags[window:window * 2])
        trend = (recent_rate - prev_rate
                 if recent_rate is not None and prev_rate is not None else None)
        return {"total": total, "reverted": reverted,
                "success_rate": round(100 * (total - reverted) / total) if total else None,
                "recent_rate": recent_rate, "prev_rate": prev_rate, "trend": trend}

    def get_activity_since(self, hours: int = 24, limit: int = 100) -> list[dict]:
        """Feed unificado de auditoria — 'o que a IA fez nas últimas `hours` horas'.
        Junta as fontes de atividade autônoma/assistida (aprendizado, tarefas do
        Coder, execuções de código, notificações e benchmarks) num só fluxo
        ordenado por tempo (mais recente primeiro). Cada evento tem a forma
        {ts, kind, icon, title, detail} para o painel de observabilidade."""
        cutoff = _now() - timedelta(hours=hours)
        events: list[dict] = []

        def _iso(dt) -> str:
            return dt.isoformat() if dt else ""

        with Session(self.engine) as s:
            for r in (s.query(LearnedTopic)
                      .filter(LearnedTopic.studied_at >= cutoff)
                      .order_by(LearnedTopic.studied_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.studied_at), "kind": "learn", "icon": "📚",
                               "title": f"Aprendeu: {r.topic}",
                               "detail": (r.summary or "")[:200], "url": r.url})

            for r in (s.query(CoderTask)
                      .filter(CoderTask.created_at >= cutoff)
                      .order_by(CoderTask.created_at.desc()).limit(limit).all()):
                bits = []
                if r.wrote: bits.append("escreveu")
                if r.ran: bits.append("rodou")
                if r.reverted: bits.append("revertido")
                events.append({"ts": _iso(r.created_at), "kind": "coder", "icon": "💻",
                               "title": f"Coder: {r.task}",
                               "detail": f"{r.steps} passos · {', '.join(bits) or 'sem alterações'}"
                                         f" · {r.duration_s}s", "reverted": r.reverted})

            for r in (s.query(Execution)
                      .filter(Execution.timestamp >= cutoff, Execution.deleted == False)
                      .order_by(Execution.timestamp.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.timestamp), "kind": "exec", "icon": "⚙️",
                               "title": f"Executou código ({r.status})",
                               "detail": (r.request or "")[:200]})

            for r in (s.query(Notification)
                      .filter(Notification.created_at >= cutoff)
                      .order_by(Notification.created_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.created_at), "kind": "notif", "icon": "🔔",
                               "title": r.message, "detail": r.kind, "url": r.link})

            for r in (s.query(BenchmarkRun)
                      .filter(BenchmarkRun.ran_at >= cutoff)
                      .order_by(BenchmarkRun.ran_at.desc()).limit(limit).all()):
                events.append({"ts": _iso(r.ran_at), "kind": "benchmark", "icon": "🎯",
                               "title": f"Autoavaliação: {r.avg_score} de nota",
                               "detail": f"{r.questions} perguntas · {r.avg_latency_ms}ms médios"})

        events.sort(key=lambda e: e["ts"], reverse=True)
        return events[:limit]

    def activity_summary(self, hours: int = 24) -> dict:
        """Contagens por tipo de atividade nas últimas `hours` horas — cabeçalho
        do painel de auditoria ('hoje: 12 estudos, 3 tarefas do Coder…')."""
        from sqlalchemy import func
        cutoff = _now() - timedelta(hours=hours)
        with Session(self.engine) as s:
            return {
                "hours": hours,
                "learned": s.query(func.count(LearnedTopic.id))
                            .filter(LearnedTopic.studied_at >= cutoff).scalar() or 0,
                "coder_tasks": s.query(func.count(CoderTask.id))
                                .filter(CoderTask.created_at >= cutoff).scalar() or 0,
                "executions": s.query(func.count(Execution.id))
                               .filter(Execution.timestamp >= cutoff,
                                       Execution.deleted == False).scalar() or 0,
                "notifications": s.query(func.count(Notification.id))
                                  .filter(Notification.created_at >= cutoff).scalar() or 0,
                "benchmarks": s.query(func.count(BenchmarkRun.id))
                               .filter(BenchmarkRun.ran_at >= cutoff).scalar() or 0,
            }

    def update_topic_summary(self, topic_id: int, summary: str) -> bool:
        """Substitui a síntese de um tópico aprendido (reparo in-place —
        não cria linha nova no log)."""
        with Session(self.engine) as s:
            row = s.get(LearnedTopic, topic_id)
            if not row:
                return False
            row.summary = summary[:2000]
            s.commit()
            return True

    def get_summary_quality(self) -> dict:
        """Qualidade da base de aprendizado: sínteses estruturadas (têm seções
        '##') vs cruas (texto corrido ≥300 chars — lixo de timeouts antigos)
        vs curtas. Alimenta o cartão de qualidade do painel Saúde."""
        from sqlalchemy import func
        with Session(self.engine) as s:
            total = s.query(func.count(LearnedTopic.id)).scalar() or 0
            structured = (s.query(func.count(LearnedTopic.id))
                          .filter(LearnedTopic.summary.like("%##%")).scalar() or 0)
            raw = (s.query(func.count(LearnedTopic.id))
                   .filter(~LearnedTopic.summary.like("%##%"),
                           func.length(LearnedTopic.summary) >= 300).scalar() or 0)
        return {"total": total, "structured": structured, "raw": raw,
                "short": total - structured - raw,
                "pct_structured": round(100 * structured / total) if total else None}

    def get_learning_stats(self) -> dict:
        from sqlalchemy import func, distinct
        today = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as s:
            # Conta tópicos ÚNICOS (não cada re-estudo) — número real de conhecimentos.
            total = s.query(func.count(distinct(LearnedTopic.topic))).scalar() or 0
            today_count = (s.query(func.count(distinct(LearnedTopic.topic)))
                           .filter(LearnedTopic.studied_at >= today).scalar() or 0)
            return {"total": total, "today": today_count}

    def get_learned_since(self, hours: int = 24, limit: int = 1000) -> list[dict]:
        """Tópicos ÚNICOS aprendidos nas últimas `hours` horas — base do digest diário."""
        from datetime import timedelta
        cutoff = _now() - timedelta(hours=hours)
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic)
                    .filter(LearnedTopic.studied_at >= cutoff)
                    .order_by(LearnedTopic.studied_at.desc())
                    .limit(limit * 3).all())
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            key = (r.topic or "").strip().lower()
            if key in seen:
                continue
            seen.add(key)
            out.append({"topic": r.topic, "url": r.url, "category": r.category,
                        "studied_at": r.studied_at.isoformat()})
            if len(out) >= limit:
                break
        return out

    def get_learning_timeline(self, days: int = 14) -> list[dict]:
        """Tópicos ÚNICOS aprendidos por dia nos últimos N dias (não conta re-estudos)."""
        from datetime import timedelta
        start = (_now() - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self.engine) as s:
            rows = (s.query(LearnedTopic.studied_at, LearnedTopic.topic)
                    .filter(LearnedTopic.studied_at >= start).all())
        per_day: dict[str, set] = {}
        for dt, topic in rows:
            d = dt.strftime("%Y-%m-%d")
            per_day.setdefault(d, set()).add((topic or "").strip().lower())
        return [
            {"date": (start + timedelta(days=i)).strftime("%Y-%m-%d"),
             "count": len(per_day.get((start + timedelta(days=i)).strftime("%Y-%m-%d"), set()))}
            for i in range(days)
        ]

    # ── Analytics ─────────────────────────────────────────────

    def analytics_messages_by_day(self, days: int = 30) -> list[dict]:
        """Contagem de mensagens do usuário por dia (últimos N dias)."""
        start = datetime.now(timezone.utc) - timedelta(days=days)
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.timestamp)
                    .filter(SessionMessage.role == "user",
                            SessionMessage.timestamp >= start)
                    .all())
        counts: dict[str, int] = {}
        for (ts,) in rows:
            d = ts.strftime("%Y-%m-%d") if ts else None
            if d:
                counts[d] = counts.get(d, 0) + 1
        return [
            {"date": (datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"),
             "count": counts.get((datetime.now(timezone.utc) - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d"), 0)}
            for i in range(days)
        ]

    def analytics_messages_by_hour(self) -> list[dict]:
        """Distribuição de mensagens do usuário por hora do dia (0–23)."""
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.timestamp)
                    .filter(SessionMessage.role == "user")
                    .all())
        counts = [0] * 24
        for (ts,) in rows:
            if ts:
                counts[ts.hour] += 1
        return [{"hour": h, "count": counts[h]} for h in range(24)]

    def analytics_top_topics(self, limit: int = 20) -> list[dict]:
        """Tópicos mais estudados (por frequência de aparecimento no learned_topics)."""
        import re
        with Session(self.engine) as s:
            rows = s.query(LearnedTopic.topic, LearnedTopic.category).all()
        freq: dict[str, dict] = {}
        for topic, cat in rows:
            key = (topic or "").strip()
            if len(key) < 3:
                continue
            if key not in freq:
                freq[key] = {"topic": key, "category": cat or "web", "count": 0}
            freq[key]["count"] += 1
        return sorted(freq.values(), key=lambda x: x["count"], reverse=True)[:limit]

    def analytics_top_words(self, limit: int = 15) -> list[dict]:
        """Palavras/termos mais frequentes nas perguntas do usuário (stopwords removidas)."""
        import re
        _STOP = {
            "de","a","o","e","em","do","da","no","na","para","com","que","se","um","uma",
            "os","as","dos","das","por","mais","como","mas","ao","às","este","esta","isso",
            "são","foi","tem","é","não","me","te","se","lhe","você","eu","ele","ela","the",
            "is","in","of","to","and","a","an","for","on","with","this","that","it","be",
            "what","how","why","when","where","can","use","get","make","do","does","using",
        }
        with Session(self.engine) as s:
            rows = (s.query(SessionMessage.content)
                    .filter(SessionMessage.role == "user")
                    .all())
        freq: dict[str, int] = {}
        for (content,) in rows:
            words = re.findall(r"\b[a-záàâãéêíóôõúüçA-Z]{3,}\b", content or "")
            for w in words:
                wl = w.lower()
                if wl not in _STOP:
                    freq[wl] = freq.get(wl, 0) + 1
        return [{"word": w, "count": c}
                for w, c in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:limit]]

    def analytics_usage_summary(self) -> dict:
        """Resumo geral: total mensagens, sessões, tópicos, estimativa de horas."""
        with Session(self.engine) as s:
            total_msgs  = s.query(SessionMessage).filter(SessionMessage.role == "user").count()
            total_sess  = s.query(SessionMessage.session_id).distinct().count()
            total_topics = s.query(LearnedTopic).count()
            # Dias distintos com atividade
            rows = s.query(SessionMessage.timestamp).filter(SessionMessage.role == "user").all()
        days_active = len({ts.strftime("%Y-%m-%d") for (ts,) in rows if ts})
        # Estimativa grosseira: ~2 min por mensagem trocada (ida + volta)
        est_hours = round(total_msgs * 2 / 60, 1)
        return {
            "total_messages": total_msgs,
            "total_sessions": total_sess,
            "total_topics_studied": total_topics,
            "days_active": days_active,
            "est_hours": est_hours,
        }

    # ── Benchmark persistente ──────────────────────────────────

    def save_benchmark_run(self, result: dict) -> int:
        """Persiste um run de benchmark no banco."""
        import json as _json
        with Session(self.engine) as s:
            row = BenchmarkRun(
                model=result.get("model", ""),
                avg_score=result.get("avg_score"),
                avg_latency_ms=result.get("avg_latency_ms"),
                total_ms=result.get("total_ms"),
                questions=result.get("questions"),
                results_json=_json.dumps(result.get("results", []), ensure_ascii=False),
            )
            s.add(row); s.commit()
            return row.id

    def get_benchmark_history(self, limit: int = 20) -> list[dict]:
        """Retorna histórico de benchmark (mais recente primeiro)."""
        import json as _json
        with Session(self.engine) as s:
            rows = (s.query(BenchmarkRun)
                    .order_by(BenchmarkRun.ran_at.desc())
                    .limit(limit).all())
        out = []
        for r in reversed(rows):  # cronológico para gráfico
            out.append({
                "id": r.id,
                "ran_at": r.ran_at.isoformat() if r.ran_at else "",
                "model": r.model,
                "avg_score": r.avg_score,
                "avg_latency_ms": r.avg_latency_ms,
                "total_ms": r.total_ms,
                "questions": r.questions,
                "results": _json.loads(r.results_json or "[]"),
            })
        return out

    # ── Reações (👍👎) ────────────────────────────────────────────

    def save_reaction(self, message_hash: str, reaction: str,
                      session_id: str = "", sources: list | None = None) -> None:
        import json as _json
        with Session(self.engine) as s:
            # Upsert: atualiza se já existe para o mesmo hash
            existing = (s.query(Reaction)
                        .filter(Reaction.message_hash == message_hash).first())
            if existing:
                existing.reaction = reaction
                existing.sources = _json.dumps(sources or [])
            else:
                s.add(Reaction(
                    message_hash=message_hash,
                    reaction=reaction,
                    session_id=session_id or "",
                    sources=_json.dumps(sources or []),
                ))
            s.commit()

    def reaction_stats(self) -> dict:
        """Contagem de 👍/👎 e fontes mais polarizadas (para o painel Analytics)."""
        import json as _json
        with Session(self.engine) as s:
            rows = s.query(Reaction).all()
        ups   = sum(1 for r in rows if r.reaction == "up")
        downs = sum(1 for r in rows if r.reaction == "down")
        # Fontes mais negativamente avaliadas
        url_neg: dict[str, int] = {}
        for r in rows:
            if r.reaction == "down":
                for url in (_json.loads(r.sources or "[]") or []):
                    url_neg[url] = url_neg.get(url, 0) + 1
        top_neg = sorted(url_neg.items(), key=lambda x: -x[1])[:5]
        return {
            "total": len(rows), "up": ups, "down": downs,
            "top_negative_sources": [{"url": u, "count": c} for u, c in top_neg],
        }
