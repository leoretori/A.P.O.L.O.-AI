"""DatabaseManager — ações reversíveis (M10, Épico 10.1): ledger de UNDO — e
rotinas automatizadas (Épico 10.2). Mixin."""

import json as _json

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage_models import Routine, UndoLog, _now


def _undo_dict(r) -> dict:
    return {"id": r.id, "kind": r.kind, "description": r.description,
            "undo_data": _json.loads(r.undo_json or "{}"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "undone": bool(r.undone),
            "undone_at": r.undone_at.isoformat() if r.undone_at else None}


def _routine_dict(r) -> dict:
    return {"id": r.id, "name": r.name, "kind": r.kind, "freq": r.freq,
            "weekday": r.weekday, "day_of_month": r.day_of_month,
            "time_of_day": r.time_of_day, "enabled": bool(r.enabled),
            "config": _json.loads(r.config_json or "{}"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "last_run": r.last_run.isoformat() if r.last_run else None}


class ActionsMixin:
    def save_undo(self, kind: str, description: str, undo_data: dict) -> int:
        """Grava os dados para desfazer uma ação recém-aplicada. Retorna o id."""
        with Session(self.engine) as s:
            row = UndoLog(kind=kind, description=(description or "")[:400],
                          undo_json=_json.dumps(undo_data or {}, ensure_ascii=False))
            s.add(row)
            s.commit()
            return row.id

    def get_undo(self, undo_id: int) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(UndoLog, undo_id)
            return _undo_dict(row) if row else None

    def list_undo(self, limit: int = 30, include_undone: bool = True) -> list[dict]:
        """Ledger de ações reversíveis, mais recentes primeiro (para o painel)."""
        with Session(self.engine) as s:
            q = s.query(UndoLog)
            if not include_undone:
                q = q.filter(UndoLog.undone == False)   # noqa: E712
            rows = q.order_by(UndoLog.id.desc()).limit(limit).all()
            return [_undo_dict(r) for r in rows]

    def mark_undone(self, undo_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(UndoLog, undo_id)
            if not row or row.undone:
                return False
            row.undone = True
            row.undone_at = _now()
            s.commit()
            return True

    def count_undo(self, pending_only: bool = False) -> int:
        with Session(self.engine) as s:
            q = s.query(func.count(UndoLog.id))
            if pending_only:
                q = q.filter(UndoLog.undone == False)   # noqa: E712
            return q.scalar() or 0

    # ── Rotinas automatizadas (M10 10.2) ──────────────────────
    def save_routine(self, name: str, kind: str, freq: str = "weekly",
                     weekday: int = 4, day_of_month: int = 1,
                     time_of_day: str = "18:00", config: dict | None = None) -> dict:
        with Session(self.engine) as s:
            row = Routine(name=(name or "")[:200], kind=kind, freq=freq,
                          weekday=int(weekday), day_of_month=int(day_of_month),
                          time_of_day=time_of_day,
                          config_json=_json.dumps(config or {}, ensure_ascii=False))
            s.add(row)
            s.commit()
            return _routine_dict(row)

    def list_routines(self, enabled_only: bool = False) -> list[dict]:
        with Session(self.engine) as s:
            q = s.query(Routine)
            if enabled_only:
                q = q.filter(Routine.enabled == True)   # noqa: E712
            return [_routine_dict(r) for r in q.order_by(Routine.id.desc()).all()]

    def get_routine(self, routine_id: int) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(Routine, routine_id)
            return _routine_dict(row) if row else None

    def set_routine_enabled(self, routine_id: int, enabled: bool) -> bool:
        with Session(self.engine) as s:
            row = s.get(Routine, routine_id)
            if not row:
                return False
            row.enabled = bool(enabled)
            s.commit()
            return True

    def mark_routine_run(self, routine_id: int, when=None) -> None:
        with Session(self.engine) as s:
            row = s.get(Routine, routine_id)
            if row:
                row.last_run = when or _now()
                s.commit()

    def delete_routine(self, routine_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(Routine, routine_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
            return True
