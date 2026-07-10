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

from src import graph
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


@router.get("/api/graph/connect")
async def graph_connect(a: str = "", b: str = "", q: str = ""):
    """M8 8.3 — 'como X se conecta com Y?'. Responde pelos conceitos que os dois
    tópicos compartilham; se não há laço direto, procura uma PONTE (tópico ligado
    aos dois). Aceita a/b OU q='como X se conecta com Y'."""
    if q and not (a and b):
        parsed = graph.parse_connect_question(q)
        if parsed:
            a, b = parsed
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return {"ok": False, "error": "informe a e b (ou q='como X se conecta com Y')"}
    if not rt.db:
        return {"ok": False, "error": "sem banco"}
    sa = await asyncio.to_thread(rt.db.get_topic_summary, a) or a
    sb = await asyncio.to_thread(rt.db.get_topic_summary, b) or b
    bridge = None
    if not graph.shared_concepts(sa, sb):
        br = await asyncio.to_thread(rt.db.find_bridge, a, b)
        if br:
            bridge = (br["bridge"], br["a_shared"], br["b_shared"])
    return {"ok": True, "a": a, "b": b, **graph.explain(a, sa, b, sb, bridge)}


@router.get("/api/graph/neighbors")
async def graph_neighbors(topic: str = "", limit: int = 12):
    """Tópicos ligados a `topic` no grafo de conhecimento (M8 8.3)."""
    if not rt.db or not topic.strip():
        return {"topic": topic, "neighbors": [], "total_edges": 0}
    ns = await asyncio.to_thread(rt.db.neighbors, topic.strip(), limit)
    total = await asyncio.to_thread(rt.db.count_edges)
    return {"topic": topic, "neighbors": ns, "total_edges": total}


@router.get("/api/learning/reviews")
async def learning_reviews():
    """M8 8.1 — estado da repetição espaçada: quantos tópicos têm revisão agendada
    e quantos estão vencidos para o próximo auto-teste."""
    if not rt.db:
        return {"total": 0, "due": 0, "due_topics": []}
    total = await asyncio.to_thread(rt.db.count_reviews)
    due = await asyncio.to_thread(rt.db.due_reviews, None, 100)
    return {"total": total, "due": len(due),
            "due_topics": [r["topic"] for r in due[:20]]}


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


@router.get("/api/briefing")
async def briefing(hours: int = 12):
    """Briefing diário (M4, Épico 4.1): resumo FALÁVEL do que importa — o que o
    A.P.O.L.O. aprendeu enquanto você esteve fora, o que vocês fizeram, a agenda
    e pendências. Retorna dados estruturados + `text` pronto p/ TTS."""
    from src.briefing import build_briefing
    hours = max(1, min(hours, 168))
    return await asyncio.to_thread(build_briefing, rt.db, rt.episodic, rt.learner,
                                   rt.profile, hours)


@router.get("/api/anticipations")
async def anticipations(hours: int = 48):
    """Antecipação útil (M17.3): metas/projetos ativos que a atividade recente
    NÃO tocou → sugestões de retomar, ancoradas nos seus hábitos."""
    def _build():
        from src.anticipation import suggest_anticipations
        recent: list[str] = []
        if rt.episodic:
            try:
                recent += [e.get("title", "") for e in rt.episodic.recent(8)]
            except Exception:
                pass
        if rt.db:
            try:
                recent += [it.get("topic", "") for it in rt.db.get_learned_since(hours)]
            except Exception:
                pass
        return {"anticipations": suggest_anticipations(rt.profile, recent)}
    return await asyncio.to_thread(_build)


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
