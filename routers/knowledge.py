"""Gestão da base de conhecimento — curadoria (duplicatas), esquecer, stats,
grafo e insights (o painel "Mente do A.P.O.L.O.").

Rotas: /api/curate/scan, /api/curate/apply, /api/knowledge/forget,
/api/knowledge/stats, /api/knowledge/graph, /api/knowledge/insights.

Extraído de app.py na M1 do JARVIS_ROADMAP. Lê os singletons via `src.runtime`.
As rotas de LEITURA da base (search/recent) ficam em routers/learning.py.
"""
import asyncio
import logging
import time

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.topics import classify_sector, SECTOR_LABELS

router = APIRouter()
logger = logging.getLogger("apolo.routers.knowledge")


# ── Curadoria de duplicatas ───────────────────────────────────────
@router.get("/api/curate/scan")
async def curate_scan():
    """Relatório (só leitura) de conhecimento duplicado (base + recall + log)."""
    if not rt.curator:
        return {"enabled": False, "total": 0, "duplicate_clusters": 0, "removable": 0,
                "chroma_duplicates": 0, "log_duplicates": 0, "clusters": []}
    data = await asyncio.to_thread(rt.curator.scan)
    return {"enabled": True, **data}


class CurateApply(BaseModel):
    ids: list[str]


@router.post("/api/curate/apply")
async def curate_apply(req: CurateApply):
    """Remove as duplicatas indicadas (ação explícita do usuário)."""
    if not rt.curator:
        return {"ok": False, "error": "Curador indisponível."}
    return await asyncio.to_thread(rt.curator.apply, req.ids)


# ── Faxina de lixo/injeção já existente na base ───────────────────
@router.get("/api/knowledge/junk/scan")
async def knowledge_junk_scan():
    """Relatório (só leitura) de conhecimento que é lixo/spam/injeção — entrou
    antes do porteiro de ingestão existir. Não remove nada; o usuário decide."""
    if not rt.knowledge_db:
        return {"enabled": False, "count": 0, "junk": []}
    junk = await asyncio.to_thread(rt.knowledge_db.scan_junk)
    return {"enabled": True, "count": len(junk), "junk": junk}


class JunkPurge(BaseModel):
    ids: list[int]


@router.post("/api/knowledge/junk/purge")
async def knowledge_junk_purge(req: JunkPurge):
    """Remove os itens-lixo indicados (ação explícita do usuário)."""
    if not rt.knowledge_db:
        return {"ok": False, "error": "base indisponível"}
    if not req.ids:
        return {"ok": True, "removed": 0}
    removed = await asyncio.to_thread(rt.knowledge_db.delete_ids, req.ids)
    return {"ok": True, "removed": removed}


# ── Esquecer / stats / grafo / insights ───────────────────────────
class ForgetRequest(BaseModel):
    id: int


@router.post("/api/knowledge/forget")
async def knowledge_forget(req: ForgetRequest):
    """Esquece um conhecimento: remove do log (SQLite), do Supabase e do RAG."""
    info = await asyncio.to_thread(rt.db.delete_learned_topic, req.id)
    if not info:
        return {"ok": False, "error": "não encontrado"}
    removed = {"sqlite": True, "supabase": 0, "rag": 0}
    if rt.knowledge_db and info.get("url"):
        removed["supabase"] = await asyncio.to_thread(rt.knowledge_db.delete_by_url, info["url"])
    if rt.rag and info.get("topic"):
        removed["rag"] = await asyncio.to_thread(rt.rag.forget_topic, info["topic"])
    return {"ok": True, "topic": info["topic"], "removed": removed}


@router.get("/api/knowledge/stats")
async def knowledge_stats():
    if not rt.knowledge_db:
        return {"enabled": False, "total": 0}
    stats = await asyncio.to_thread(rt.knowledge_db.stats)
    return {"enabled": True, **stats}


@router.get("/api/knowledge/graph")
async def knowledge_graph():
    """Mapa de conhecimento: centro (A.P.O.L.O.) → setores → tópicos de exemplo.
    Monta um grafo a partir dos tópicos aprendidos, agrupados por setor."""
    # Cache curto: o mapa muda devagar (só com novos estudos) e era reconstruído
    # do zero a cada abertura do painel.
    cache = knowledge_graph._cache
    if cache and (time.time() - cache[0]) < 60:
        return cache[1]

    def _build() -> dict:
        history = rt.db.get_learning_history(limit=400) if rt.db else []
        groups: dict[str, list[str]] = {}
        for h in history:
            topic = (h.get("topic") or "").strip()
            if not topic:
                continue
            sec = classify_sector(topic)
            groups.setdefault(sec, [])
            if len(groups[sec]) < 5:
                groups[sec].append(topic[:60])
        # Ordena setores por volume e limita para o mapa não virar sopa.
        ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
        nodes = [{"id": "apolo", "label": "A.P.O.L.O.", "type": "core"}]
        edges = []
        for sec, topics in ranked:
            sid = f"sec::{sec}"
            nodes.append({"id": sid, "label": SECTOR_LABELS.get(sec, sec),
                          "type": "sector", "sector": sec, "count": len(topics)})
            edges.append({"source": "apolo", "target": sid})
            for i, t in enumerate(topics[:4]):
                tid = f"{sid}::t{i}"
                nodes.append({"id": tid, "label": t, "type": "topic"})
                edges.append({"source": sid, "target": tid})
        return {"nodes": nodes, "edges": edges, "sectors": len(ranked)}

    try:
        result = await asyncio.to_thread(_build)
        knowledge_graph._cache = (time.time(), result)
        return result
    except Exception as e:
        logger.warning(f"knowledge_graph: {e}")
        return {"nodes": [], "edges": [], "sectors": 0}


knowledge_graph._cache = None  # (timestamp, payload) — cache curto do mapa


@router.get("/api/knowledge/insights")
async def knowledge_insights():
    """Auto-percepção do A.P.O.L.O. — o que ele sabe + estado vivo do aprendizado.
    Alimenta o painel 'Mente do A.P.O.L.O.'."""
    # As três fontes são independentes → busca em paralelo (antes era sequencial).
    async def _insights():
        if not rt.knowledge_db:
            return {"enabled": False, "total": 0, "sampled": False,
                    "categories": [], "sectors": [], "domains": [], "recent": []}
        return {"enabled": True, **(await asyncio.to_thread(rt.knowledge_db.insights))}

    async def _status():
        return await asyncio.to_thread(rt.learner.get_status) if rt.learner else {}

    async def _timeline():
        if not rt.db:
            return []
        try:
            return await asyncio.to_thread(rt.db.get_learning_timeline, 14)
        except Exception:
            return []

    base, ls, timeline = await asyncio.gather(_insights(), _status(), _timeline())
    base["learning"] = {
        "running": ls.get("running", False),
        "total_learned": ls.get("total_learned", 0),
        "learned_today": ls.get("learned_today", 0),
        "self_directed_count": ls.get("self_directed_count", 0),
        "throughput_hour": ls.get("throughput_hour", 0),
        "next_studies": ls.get("next_studies", []),
        "gap_count": ls.get("gap_count", 0),
        "recent_gaps": ls.get("recent_gaps", []),
        "agents": ls.get("agents", []),
    }
    base["timeline"] = timeline
    return base
