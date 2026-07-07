"""DatabaseManager — permissões de agência + auditoria de ferramentas (M6 6.1).

Mixin: guarda os consentimentos do usuário (grants por escopo) e o log de toda
invocação de ferramenta que toca o mundo. É a base da agência com permissão."""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.storage_models import _now, Permission, ToolAudit


class PermissionsMixin:
    # ── Consentimentos ────────────────────────────────────────
    def grant_permission(self, scope: str, note: str = "") -> dict:
        scope = (scope or "").strip()
        with Session(self.engine) as s:
            row = s.get(Permission, scope)
            if row:
                row.granted = True
                row.granted_at = _now()
                if note:
                    row.note = note[:500]
            else:
                row = Permission(scope=scope, granted=True, note=note[:500])
                s.add(row)
            s.commit()
            return _perm_dict(row)

    def revoke_permission(self, scope: str) -> bool:
        with Session(self.engine) as s:
            row = s.get(Permission, (scope or "").strip())
            if not row:
                return False
            row.granted = False
            s.commit()
            return True

    def is_permission_granted(self, scope: str) -> bool:
        if not scope:
            return True                     # ferramenta sem escopo é livre (segura)
        with Session(self.engine) as s:
            row = s.get(Permission, scope)
            return bool(row and row.granted)

    def permission_note(self, scope: str) -> str:
        """Note do grant — para files.read é a allowlist de pastas autorizadas."""
        with Session(self.engine) as s:
            row = s.get(Permission, (scope or "").strip())
            return (row.note or "") if row else ""

    def list_permissions(self) -> list[dict]:
        with Session(self.engine) as s:
            return [_perm_dict(r) for r in s.query(Permission).all()]

    # ── Auditoria de ferramentas ──────────────────────────────
    def log_tool(self, tool: str, scope: str, allowed: bool,
                 args: str = "", result: str = "") -> int:
        with Session(self.engine) as s:
            row = ToolAudit(tool=tool[:60], scope=(scope or "")[:60], allowed=allowed,
                            args=(args or "")[:500], result=(result or "")[:500])
            s.add(row); s.commit()
            return row.id

    def list_tool_audit(self, limit: int = 50, hours: int | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = s.query(ToolAudit)
            if hours:
                q = q.filter(ToolAudit.created_at >= _now() - timedelta(hours=hours))
            rows = q.order_by(ToolAudit.created_at.desc()).limit(limit).all()
            return [_audit_dict(r) for r in rows]


def _perm_dict(r) -> dict:
    return {"scope": r.scope, "granted": bool(r.granted), "note": r.note or "",
            "granted_at": r.granted_at.isoformat() if r.granted_at else None}


def _audit_dict(r) -> dict:
    return {"id": r.id, "tool": r.tool, "scope": r.scope, "allowed": bool(r.allowed),
            "args": r.args, "result": r.result,
            "created_at": r.created_at.isoformat() if r.created_at else None}
