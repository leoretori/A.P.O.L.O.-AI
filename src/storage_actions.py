"""DatabaseManager — ações reversíveis (M10, Épico 10.1): ledger de UNDO. Mixin."""

import json as _json

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage_models import UndoLog, _now


def _undo_dict(r) -> dict:
    return {"id": r.id, "kind": r.kind, "description": r.description,
            "undo_data": _json.loads(r.undo_json or "{}"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "undone": bool(r.undone),
            "undone_at": r.undone_at.isoformat() if r.undone_at else None}


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
