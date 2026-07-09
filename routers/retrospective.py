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
