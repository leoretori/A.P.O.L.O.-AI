"""Endpoints do aprendizado autônomo.

Rotas: /api/learning/* (start, stop, repair, status, stream, study-now,
history, timeline, agents), /api/digest e as duas rotas de leitura da base
(/api/knowledge/search, /api/knowledge/recent).

Extraído de app.py na M1 do JARVIS_ROADMAP. Lê os singletons via `src.runtime`
(preenchidos no startup), evitando import circular com app.py.
"""
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src import runtime as rt
from src.topics import classify_sector, SECTOR_LABELS

router = APIRouter()


class StudyRequest(BaseModel):
    topic: str


def _clean_topic(t: str) -> str:
    """Tira molduras do título para exibição no digest."""
    t = (t or "").strip()
    if t.startswith("Ideias centrais do livro "):
        t = "📖 " + t[len("Ideias centrais do livro "):]
    t = t.replace(" (enciclopédia)", "")
    return t[:90]


@router.post("/api/learning/start")
async def start_learning():
    await rt.learner.start()
    return {"ok": True, "status": rt.learner.get_status()}


@router.post("/api/learning/stop")
async def stop_learning():
    await rt.learner.stop()
    return {"ok": True, "status": rt.learner.get_status()}


@router.post("/api/learning/repair")
async def learning_repair(limit: int = 8):
    """Repara sínteses cruas (timeouts antigos salvaram texto truncado como
    conhecimento): re-sintetiza em background e avisa via notificação."""
    if not rt.learner or not rt.db:
        return {"ok": False, "error": "learner indisponível"}
    rows = await asyncio.to_thread(rt.db.get_learning_history, 300)
    found = sum(1 for r in rows if rt.learner._looks_raw(r.get("summary", "")))
    if not found:
        return {"ok": True, "found": 0}
    asyncio.create_task(rt.learner.repair_raw_summaries(limit))
    return {"ok": True, "found": found, "started": min(found, limit)}


@router.get("/api/learning/status")
async def learning_status():
    return rt.learner.get_status() if rt.learner else {"running": False}


@router.get("/api/learning/stream")
async def learning_stream():
    """SSE push do status do aprendizado — substitui o polling de 3 s/3 s do frontend.
    O cliente conecta uma vez e recebe updates quando algo muda, sem polling."""
    async def _events():
        last_hash = None
        while True:
            try:
                st = rt.learner.get_status() if rt.learner else {"running": False}
                # Serializa e compara hash — só envia quando o estado mudou
                payload = json.dumps(st, sort_keys=True)
                h = hash(payload)
                if h != last_hash:
                    last_hash = h
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)
    return StreamingResponse(
        _events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/learning/study-now")
async def study_now(req: StudyRequest):
    """Estuda um tópico imediatamente, independente do modo estar ligado."""
    if not rt.learner:
        return {"ok": False, "error": "Learner não inicializado"}
    result = await rt.learner.study_now(req.topic)
    return result


@router.get("/api/learning/history")
async def learning_history(limit: int = 200):
    if not rt.db:
        return []
    items = rt.db.get_learning_history(limit=limit)
    for it in items:
        it["sector"] = classify_sector(it.get("topic", ""))
    return items


@router.get("/api/learning/timeline")
async def learning_timeline(days: int = 14):
    if not rt.db:
        return []
    return await asyncio.to_thread(rt.db.get_learning_timeline, days)


@router.get("/api/digest")
async def digest(hours: int = 24):
    """Digest 'o que aprendi' — tópicos recentes agrupados por setor."""
    if not rt.db:
        return {"hours": hours, "total": 0, "sectors": []}
    items = await asyncio.to_thread(rt.db.get_learned_since, hours)
    by_sector: dict[str, list[str]] = {}
    for it in items:
        s = classify_sector(it.get("topic", ""))
        by_sector.setdefault(s, []).append(_clean_topic(it.get("topic", "")))
    sectors = sorted(
        ({"sector": s, "label": SECTOR_LABELS.get(s, s), "count": len(v), "samples": v[:5]}
         for s, v in by_sector.items()),
        key=lambda x: x["count"], reverse=True,
    )
    return {"hours": hours, "total": len(items), "sectors": sectors,
            "generated_at": datetime.now().isoformat()}


@router.get("/api/learning/agents")
async def learning_agents():
    """Status em tempo real de cada mini-agente."""
    if not rt.learner:
        return []
    status = rt.learner.get_status()
    return status.get("agents", [])


@router.get("/api/knowledge/search")
async def search_knowledge(q: str = ""):
    if not q or not rt.knowledge_db:
        return []
    results = await asyncio.to_thread(rt.knowledge_db.search, q, 5)
    return results


@router.get("/api/knowledge/recent")
async def knowledge_recent(limit: int = 10):
    """Últimos tópicos aprendidos com sumário."""
    if not rt.db:
        return []
    return rt.db.get_learning_history(limit=limit)
