"""Retrospectiva do ano (M12, Épico 12.2): o que o A.P.O.L.O. fez e o que sugere
para o ano 2 — um resumo FALÁVEL (DoD do M12).

  GET /api/retrospective → {highlights, year_two_themes, text}
"""
import asyncio

from fastapi import APIRouter

from src import retrospective as R
from src import runtime as rt

router = APIRouter()


def _gather_year_data() -> dict:
    """Números do ano, das fontes que já medimos (tudo tolerante a falha)."""
    db = rt.db
    data: dict = {}
    try:
        data["total_topics"] = db.get_learning_stats().get("total", 0)
    except Exception:
        pass
    try:
        data["active_days"] = db.analytics_usage_summary().get("days_active", 0)
    except Exception:
        pass
    try:
        cs = db.get_coder_stats()
        data["coder"] = {"total": cs.get("total", 0), "success_rate": cs.get("success_rate")}
    except Exception:
        pass
    try:
        latest = db.latest_eval()
        if latest:
            data["eval"] = {"score": latest.get("score"),
                            "hallucination_rate": latest.get("hallucination_rate")}
    except Exception:
        pass
    try:
        rs = db.reaction_stats()
        data["feedback"] = {"up": rs.get("up", 0), "down": rs.get("down", 0)}
    except Exception:
        pass
    try:
        data["projects_done"] = len(db.list_self_projects(status="done"))
    except Exception:
        pass
    return data


@router.get("/api/retrospective")
async def retrospective():
    from routers.projects import _gather_signals
    data, signals = await asyncio.gather(
        asyncio.to_thread(_gather_year_data),
        asyncio.to_thread(_gather_signals),
    )
    return R.build_retrospective(data, signals)


def _read_blind_eval_last() -> dict:
    """Último resultado da avaliação às cegas (M28), se houver — mesmo
    arquivo que `routers/nano.py` já lê; leitura tolerante a ausência."""
    import json
    import os
    path = "data/nano/blind_eval_last.json"
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {"n": d.get("n", 0), "win_rate": d.get("nano_win_rate")}
    except Exception:
        return {}


def _gather_year2_data() -> dict:
    """Números do Ano 2 — Nano, agência/visão, loop fechado de projetos (M24.1)
    somados ao que o Ano 1 já media (aprendizado, eval, feedback). Tudo
    tolerante a falha, como o coletor do Ano 1."""
    db = rt.db
    data = _gather_year_data()   # reusa aprendizado/eval/feedback do Ano 1
    try:
        data["nano"] = db.nano_coverage().get("overall", {})
    except Exception:
        pass
    try:
        data["blind_eval"] = _read_blind_eval_last()
    except Exception:
        pass
    try:
        outcomes = db.list_project_outcomes(limit=500)
        data["projects_measured"] = {
            "total": len(outcomes),
            "improved": sum(1 for o in outcomes if o.get("improved") is True),
        }
    except Exception:
        pass
    try:
        from src.vision_read import capabilities
        cap = capabilities(None)
        data["vision_shipped"] = bool(cap.get("screen") or cap.get("pdf"))
    except Exception:
        pass
    return data


@router.get("/api/retrospective2")
async def retrospective2():
    """Retrospectiva do ANO 2 (M24, Épico 24.3): o que o A.P.O.L.O. passou a
    saber fazer no ano — com números — e o que propõe para o Ano 3."""
    from src import retrospective2 as R2
    data = await asyncio.to_thread(_gather_year2_data)
    return R2.build_retrospective2(data)
