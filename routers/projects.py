"""Projetos autodirigidos (M12, Épico 12.1).

  GET    /api/projects/suggest   → metas propostas a partir das próprias métricas
  POST   /api/projects/adopt     → adota uma meta como projeto (com passos)
  GET    /api/projects           → lista os projetos (status opcional)
  POST   /api/projects/{id}/task → marca/desmarca um passo
  POST   /api/projects/{id}/status → active | done | dismissed
  DELETE /api/projects/{id}      → remove

O `suggest` é read-only e determinístico; adotar/executar é decisão do Leo
(automelhoria SUPERVISIONADA).
"""
import asyncio

from fastapi import APIRouter

from src import projects as P
from src import runtime as rt


def _gather_signals() -> dict:
    """Coleta os sinais de saúde do próprio sistema (tudo que já medimos)."""
    db = rt.db
    sig: dict = {}
    try:
        q = db.get_summary_quality()
        sig["pct_structured"] = q.get("pct_structured")
        sig["raw_summaries"] = q.get("raw", 0)
    except Exception:
        pass
    try:
        sig["coder_success"] = db.get_coder_stats().get("success_rate")
    except Exception:
        pass
    try:
        sig["duplicates"] = db.count_topic_duplicates()
    except Exception:
        pass
    try:
        sig["down_votes"] = db.reaction_stats().get("down", 0)
    except Exception:
        pass
    try:
        latest = db.latest_eval()
        if latest:
            sig["hallucination_rate"] = latest.get("hallucination_rate")
        sig["eval_score_trend"] = db.eval_trend().get("score_trend")
    except Exception:
        pass
    if rt.learner is not None:
        sig["gap_count"] = getattr(rt.learner, "_gap_count", 0)
    return sig


router = APIRouter()


@router.get("/api/projects/suggest")
async def suggest():
    """Metas que o A.P.O.L.O. propõe agora (as que já viraram projeto são omitidas)."""
    signals = await asyncio.to_thread(_gather_signals)
    goals = P.propose_goals(signals)
    out = []
    for g in goals:
        if await asyncio.to_thread(rt.db.has_active_project, g["kind"]):
            continue
        out.append({**g, "tasks": P.break_into_tasks(g)})
    return {"signals": signals, "count": len(out), "goals": out}


@router.post("/api/projects/adopt")
async def adopt(payload: dict):
    """Adota uma meta como projeto com os passos concretos."""
    p = payload or {}
    kind = (p.get("kind") or "").strip()
    title = (p.get("title") or "").strip()
    if not kind or not title:
        return {"ok": False, "error": "informe 'kind' e 'title'"}
    tasks = p.get("tasks") or P.break_into_tasks({"kind": kind})
    proj = await asyncio.to_thread(rt.db.save_self_project, kind, title, p.get("why", ""), tasks)
    return {"ok": True, "project": proj}


@router.get("/api/projects")
async def list_projects(status: str = ""):
    items = await asyncio.to_thread(rt.db.list_self_projects, status or None)
    return {"count": len(items), "projects": items}


@router.post("/api/projects/{project_id}/task")
async def toggle_task(project_id: int, payload: dict):
    idx = (payload or {}).get("index")
    done = (payload or {}).get("done", True)
    if idx is None:
        return {"ok": False, "error": "informe 'index'"}
    proj = await asyncio.to_thread(rt.db.set_project_task, project_id, int(idx), bool(done))
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    return {"ok": True, "project": proj}


@router.post("/api/projects/{project_id}/status")
async def set_status(project_id: int, payload: dict):
    status = (payload or {}).get("status", "")
    if status not in ("active", "done", "dismissed"):
        return {"ok": False, "error": "status inválido"}
    ok = await asyncio.to_thread(rt.db.set_project_status, project_id, status)
    return {"ok": ok}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: int):
    ok = await asyncio.to_thread(rt.db.delete_self_project, project_id)
    return {"ok": ok}
