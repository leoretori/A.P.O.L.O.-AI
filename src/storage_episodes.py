"""DatabaseManager — memória episódica/autobiográfica (M2, Épico 2.2). Mixin.

Persiste episódios (conversas resumidas e datadas) e os recupera por janela de
tempo — base do recall temporal ('o que fizemos ontem?')."""

import json
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage_models import _now, Episode, SessionMessage


class EpisodesMixin:
    def save_episode(self, title: str, summary: str = "", session_id: str = "",
                     occurred_at: datetime | None = None,
                     tags: list[str] | None = None) -> int:
        """Grava um episódio. Se a sessão já tem episódio, ATUALIZA (uma conversa
        = um episódio) em vez de duplicar."""
        with Session(self.engine) as s:
            existing = None
            if session_id:
                existing = (s.query(Episode)
                            .filter(Episode.session_id == session_id).first())
            if existing:
                existing.title = title[:300]
                existing.summary = (summary or "")[:2000]
                existing.tags = json.dumps(tags or [])
                if occurred_at:
                    existing.occurred_at = occurred_at
                s.commit()
                return existing.id
            row = Episode(
                session_id=session_id or None,
                title=title[:300],
                summary=(summary or "")[:2000],
                tags=json.dumps(tags or []),
                occurred_at=occurred_at or _now(),
            )
            s.add(row); s.commit()
            return row.id

    def get_episode_for_session(self, session_id: str) -> dict | None:
        with Session(self.engine) as s:
            row = (s.query(Episode)
                   .filter(Episode.session_id == session_id).first())
            return _episode_dict(row) if row else None

    def get_episodes_between(self, start: datetime, end: datetime,
                             limit: int = 50) -> list[dict]:
        """Episódios cujo `occurred_at` cai em [start, end), mais recente primeiro."""
        with Session(self.engine) as s:
            rows = (s.query(Episode)
                    .filter(Episode.occurred_at >= start, Episode.occurred_at < end)
                    .order_by(Episode.occurred_at.desc())
                    .limit(limit).all())
            return [_episode_dict(r) for r in rows]

    def recent_episodes(self, limit: int = 20) -> list[dict]:
        with Session(self.engine) as s:
            rows = (s.query(Episode)
                    .order_by(Episode.occurred_at.desc())
                    .limit(limit).all())
            return [_episode_dict(r) for r in rows]

    def sessions_pending_episode(self, inactive_before: datetime,
                                 min_messages: int = 4, limit: int = 20) -> list[dict]:
        """Sessões prontas para virar episódio: inativas desde antes de
        `inactive_before`, com pelo menos `min_messages` mensagens e que ainda
        NÃO têm episódio. Base da consolidação noturna (Épico 2.3)."""
        with Session(self.engine) as s:
            done = {sid for (sid,) in s.query(Episode.session_id)
                    .filter(Episode.session_id.isnot(None)).all()}
            rows = (s.query(SessionMessage.session_id,
                            func.max(SessionMessage.timestamp).label("last"),
                            func.count(SessionMessage.id).label("cnt"))
                    .group_by(SessionMessage.session_id)
                    .having(func.count(SessionMessage.id) >= min_messages)
                    .having(func.max(SessionMessage.timestamp) < inactive_before)
                    .all())
        out = [{"session_id": sid, "last_active": last, "message_count": cnt}
               for sid, last, cnt in rows if sid and sid not in done]
        out.sort(key=lambda x: str(x["last_active"]), reverse=True)
        return out[:limit]

    def search_episodes(self, query: str, limit: int = 10) -> list[dict]:
        """Busca textual simples (LIKE) em título e resumo dos episódios."""
        q = (query or "").strip()
        if len(q) < 2:
            return []
        like = f"%{q}%"
        with Session(self.engine) as s:
            rows = (s.query(Episode)
                    .filter(Episode.title.ilike(like) | Episode.summary.ilike(like))
                    .order_by(Episode.occurred_at.desc())
                    .limit(limit).all())
            return [_episode_dict(r) for r in rows]


def _episode_dict(r) -> dict:
    try:
        tags = json.loads(r.tags or "[]")
    except Exception:
        tags = []
    return {
        "id": r.id,
        "session_id": r.session_id,
        "title": r.title,
        "summary": r.summary,
        "tags": tags,
        "occurred_at": r.occurred_at.isoformat() if r.occurred_at else None,
    }
