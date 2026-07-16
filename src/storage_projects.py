"""DatabaseManager — projetos autodirigidos (M12, Épico 12.1). Mixin."""

import json as _json

from sqlalchemy.orm import Session

from src.storage_models import ProjectOutcome, SelfProject, _now


def _outcome_dict(r) -> dict:
    return {"id": r.id, "project_id": r.project_id, "kind": r.kind, "label": r.label,
            "baseline": r.baseline, "current": r.current, "delta": r.delta,
            "improved": r.improved, "auto": bool(r.auto),
            "measured_at": r.measured_at.isoformat() if r.measured_at else None}


def _project_dict(r) -> dict:
    from src.projects import project_progress
    tasks = _json.loads(r.tasks_json or "[]")
    try:
        baseline = _json.loads(getattr(r, "baseline_json", "") or "null")
    except Exception:
        baseline = None
    return {"id": r.id, "kind": r.kind, "title": r.title, "why": r.why,
            "tasks": tasks, "status": r.status, "progress": project_progress(tasks),
            "baseline": baseline,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


class ProjectsMixin:
    def save_self_project(self, kind: str, title: str, why: str, tasks: list[str],
                          baseline: dict | None = None) -> dict:
        rows = [{"text": t, "done": False} for t in (tasks or [])]
        with Session(self.engine) as s:
            row = SelfProject(kind=kind, title=title[:300], why=(why or "")[:300],
                              tasks_json=_json.dumps(rows, ensure_ascii=False),
                              baseline_json=_json.dumps(baseline, ensure_ascii=False)
                              if baseline is not None else "")
            s.add(row)
            s.commit()
            return _project_dict(row)

    def list_self_projects(self, status: str | None = None) -> list[dict]:
        with Session(self.engine) as s:
            q = s.query(SelfProject)
            if status:
                q = q.filter(SelfProject.status == status)
            return [_project_dict(r) for r in q.order_by(SelfProject.id.desc()).all()]

    def get_self_project(self, project_id: int) -> dict | None:
        with Session(self.engine) as s:
            row = s.get(SelfProject, project_id)
            return _project_dict(row) if row else None

    def set_project_task(self, project_id: int, index: int, done: bool) -> dict | None:
        """Marca/desmarca uma tarefa. Se todas ficarem feitas, o projeto vira 'done'."""
        with Session(self.engine) as s:
            row = s.get(SelfProject, project_id)
            if not row:
                return None
            tasks = _json.loads(row.tasks_json or "[]")
            if not (0 <= index < len(tasks)):
                return _project_dict(row)
            tasks[index]["done"] = bool(done)
            row.tasks_json = _json.dumps(tasks, ensure_ascii=False)
            row.updated_at = _now()
            if tasks and all(t.get("done") for t in tasks):
                row.status = "done"
            elif row.status == "done":
                row.status = "active"     # reabriu ao desmarcar
            s.commit()
            return _project_dict(row)

    def set_project_status(self, project_id: int, status: str) -> bool:
        with Session(self.engine) as s:
            row = s.get(SelfProject, project_id)
            if not row:
                return False
            row.status = status
            row.updated_at = _now()
            s.commit()
            return True

    def delete_self_project(self, project_id: int) -> bool:
        with Session(self.engine) as s:
            row = s.get(SelfProject, project_id)
            if not row:
                return False
            s.delete(row)
            s.commit()
            return True

    def has_active_project(self, kind: str) -> bool:
        """Evita propor de novo uma meta que já virou projeto ativo."""
        with Session(self.engine) as s:
            return s.query(SelfProject).filter(
                SelfProject.kind == kind,
                SelfProject.status.in_(["active", "done"])).first() is not None

    # ── Curva de resultados (M24.1) — cada medição de outcome vira histórico ──
    def save_project_outcome(self, project_id: int, kind: str, label: str,
                             baseline, current, delta, improved,
                             auto: bool = False) -> dict:
        with Session(self.engine) as s:
            row = ProjectOutcome(project_id=project_id, kind=kind, label=label[:120],
                                 baseline=baseline, current=current, delta=delta,
                                 improved=improved, auto=auto)
            s.add(row)
            s.commit()
            return _outcome_dict(row)

    def list_project_outcomes(self, kind: str | None = None, limit: int = 100) -> list[dict]:
        """A curva de capacidade (M24.2 lê isto): mais recente primeiro."""
        with Session(self.engine) as s:
            q = s.query(ProjectOutcome)
            if kind:
                q = q.filter(ProjectOutcome.kind == kind)
            rows = q.order_by(ProjectOutcome.measured_at.desc()).limit(limit).all()
            return [_outcome_dict(r) for r in rows]
