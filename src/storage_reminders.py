"""DatabaseManager — lembretes/follow-ups (M4, Épico 4.2). Mixin.

Persiste lembretes (detectados em conversas ou manuais) e os recupera: pendentes
para o briefing e vencidos para o scheduler resurfacear."""

from datetime import datetime

from sqlalchemy.orm import Session

from src.storage_models import _now, Reminder


class RemindersMixin:
    def save_reminder(self, text: str, due_at: datetime | None = None,
                      session_id: str = "") -> int | None:
        """Grava um lembrete. Dedup: se já existe um PENDENTE com o mesmo texto,
        não duplica (retorna None)."""
        text = (text or "").strip()
        if len(text) < 2:
            return None
        with Session(self.engine) as s:
            dup = (s.query(Reminder.id)
                   .filter(Reminder.text == text[:300], Reminder.done == False).first())
            if dup:
                return None
            row = Reminder(text=text[:300], due_at=due_at, session_id=session_id or None)
            s.add(row); s.commit()
            return row.id

    def list_reminders(self, pending_only: bool = True, limit: int = 50) -> list[dict]:
        with Session(self.engine) as s:
            q = s.query(Reminder)
            if pending_only:
                q = q.filter(Reminder.done == False)
            rows = (q.order_by(Reminder.due_at.is_(None), Reminder.due_at.asc(),
                               Reminder.created_at.desc())
                    .limit(limit).all())
            return [_reminder_dict(r) for r in rows]

    def mark_reminder_done(self, reminder_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(Reminder, reminder_id)
            if not row:
                return False
            row.done = True
            s.commit()
            return True

    def due_reminders(self, now: datetime | None = None) -> list[dict]:
        """Lembretes vencidos (due_at <= agora), ainda não concluídos nem avisados
        — o scheduler resurfaceia como notificação."""
        now = now or _now()
        with Session(self.engine) as s:
            rows = (s.query(Reminder)
                    .filter(Reminder.done == False, Reminder.notified == False,
                            Reminder.due_at.isnot(None), Reminder.due_at <= now)
                    .order_by(Reminder.due_at.asc()).all())
            return [_reminder_dict(r) for r in rows]

    def mark_reminder_notified(self, reminder_id: int) -> None:
        with Session(self.engine) as s:
            row = s.get(Reminder, reminder_id)
            if row:
                row.notified = True
                s.commit()


def _reminder_dict(r) -> dict:
    return {
        "id": r.id,
        "text": r.text,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "due_at": r.due_at.isoformat() if r.due_at else None,
        "session_id": r.session_id,
        "done": r.done,
    }
