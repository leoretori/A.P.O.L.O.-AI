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
    # M19.3: fotografa a métrica que motivou a meta AGORA (o "antes"), para
    # medir o antes→depois quando o projeto concluir.
    from src.project_exec import capture_baseline
    baseline = await asyncio.to_thread(capture_baseline, kind, _exec_ctx())
    proj = await asyncio.to_thread(rt.db.save_self_project, kind, title,
                                   p.get("why", ""), tasks, baseline)
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


# ─────────────────────────────────────────────────────────────────────────
# Execução supervisionada (M19.1): do propor ao FAZER. Os passos ganham um
# executor real, sempre no contrato de dois passos (preview → run).
# ─────────────────────────────────────────────────────────────────────────

def _exec_ctx():
    from src.project_exec import ExecContext
    return ExecContext(db=rt.db, rag=rt.rag, learner=rt.learner)


@router.get("/api/projects/{project_id}/plan")
async def project_plan(project_id: int):
    """Os passos que o A.P.O.L.O. pode EXECUTAR sozinho neste projeto (os demais
    seguem manuais, no checklist)."""
    from src.project_exec import plan_for
    proj = await asyncio.to_thread(rt.db.get_self_project, project_id)
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    return {"ok": True, "project": proj, "plan": plan_for(proj)}


@router.post("/api/projects/{project_id}/steps/{key}/preview")
async def project_step_preview(project_id: int, key: str):
    """Fase 1 — prévia do passo, SEM efeito (o que rodá-lo faria)."""
    from src.project_exec import preview_step
    proj = await asyncio.to_thread(rt.db.get_self_project, project_id)
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    return await asyncio.to_thread(preview_step, key, _exec_ctx())


@router.post("/api/projects/{project_id}/steps/{key}/run")
async def project_step_run(project_id: int, key: str, payload: dict | None = None):
    """Fase 2 — executa o passo de fato e RE-MEDE. Se `task_index` vier, marca
    aquele item do checklist como feito (a execução avança o projeto)."""
    from src.project_exec import run_step
    proj = await asyncio.to_thread(rt.db.get_self_project, project_id)
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    out = await asyncio.to_thread(run_step, key, _exec_ctx())
    if out.get("ok"):
        idx = (payload or {}).get("task_index")
        if idx is not None:
            proj = await asyncio.to_thread(rt.db.set_project_task, project_id, int(idx), True)
        out["project"] = proj
    return out


@router.post("/api/projects/{project_id}/plan/run")
async def project_plan_run(project_id: int, payload: dict | None = None):
    """Executa o PLANO multi-passo (M19.2): roda os passos seguros sozinho e PARA
    num checkpoint para confirmar cada passo sensível. `confirm` autoriza o passo
    do checkpoint atual; chame de novo para seguir até o próximo. Retomável."""
    from src.project_exec import run_plan
    proj = await asyncio.to_thread(rt.db.get_self_project, project_id)
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    confirm = (payload or {}).get("confirm")
    out = await asyncio.to_thread(run_plan, proj, _exec_ctx(), confirm=confirm)
    return {"ok": True, **out}


@router.get("/api/projects/{project_id}/outcome")
async def project_outcome(project_id: int):
    """Fecha o loop propõe→faz→MEDE (M19.3): re-mede a métrica que motivou o
    projeto e mostra o antes→depois (melhorou de verdade?)."""
    from src.project_exec import outcome
    proj = await asyncio.to_thread(rt.db.get_self_project, project_id)
    if proj is None:
        return {"ok": False, "error": "projeto não encontrado"}
    return {"ok": True, "outcome": await asyncio.to_thread(outcome, proj, _exec_ctx())}
