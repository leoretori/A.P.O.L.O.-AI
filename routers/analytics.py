"""Métricas do A.P.O.L.O. — benchmark de qualidade, analytics de uso e reações
(feedback 👍/👎).

Rotas: /api/benchmark/run|history|diff, /api/analytics, /api/reactions,
/api/reactions/stats.

Extraído de app.py na M1 do JARVIS_ROADMAP. O histórico de benchmark é um cache
em memória DESTA sessão (não vem do banco) — mora aqui no módulo. O modelo de
chat é lido via `rt.get_chat_model()` porque ele é reatribuído em runtime.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.llm import KEEP_ALIVE
from src.benchmark import run_benchmark, diff_runs
import os

router = APIRouter()

# Cache em memória do benchmark (só desta sessão; o persistente fica no banco).
_benchmark_history: list[dict] = []
_BENCHMARK_HISTORY_MAX = int(os.getenv("BENCHMARK_HISTORY_MAX", 10))


@router.post("/api/benchmark/run")
async def benchmark_run():
    """Executa o benchmark de qualidade, persiste no banco e retorna métricas."""
    result = await run_benchmark(chat_model=rt.get_chat_model(), keep_alive=KEEP_ALIVE)
    result["timestamp"] = datetime.now().isoformat()
    # Persiste no banco (sobrevive ao restart) + memória (acesso rápido)
    await asyncio.to_thread(rt.db.save_benchmark_run, result)
    _benchmark_history.append(result)
    if len(_benchmark_history) > _BENCHMARK_HISTORY_MAX:
        _benchmark_history.pop(0)
    return result


@router.get("/api/benchmark/history")
async def benchmark_history():
    """Histórico de benchmark — banco (persistente) + memória desta sessão."""
    saved = await asyncio.to_thread(rt.db.get_benchmark_history, 20)
    return {"runs": len(saved), "history": saved}


@router.get("/api/analytics")
async def analytics():
    """Painel de analytics: uso, perguntas mais frequentes, tópicos, benchmark."""
    summary, by_day, by_hour, top_topics, top_words, bench = await asyncio.gather(
        asyncio.to_thread(rt.db.analytics_usage_summary),
        asyncio.to_thread(rt.db.analytics_messages_by_day, 30),
        asyncio.to_thread(rt.db.analytics_messages_by_hour),
        asyncio.to_thread(rt.db.analytics_top_topics, 20),
        asyncio.to_thread(rt.db.analytics_top_words, 15),
        asyncio.to_thread(rt.db.get_benchmark_history, 10),
    )
    return {
        "summary": summary,
        "messages_by_day": by_day,
        "messages_by_hour": by_hour,
        "top_topics": top_topics,
        "top_words": top_words,
        "benchmark_history": bench,
    }


class ReactionRequest(BaseModel):
    message_hash: str
    reaction: str           # "up" ou "down"
    session_id: str = ""
    sources: list[str] = []
    reason: str = ""        # M9 9.2: por que (texto do Leo, opcional)
    question: str = ""      # pergunta que gerou a resposta
    answer: str = ""        # trecho da resposta avaliada


@router.post("/api/reactions")
async def save_reaction(req: ReactionRequest):
    """Salva feedback 👍/👎 (+ 'por quê') no banco. Um 👎 com motivo vira dado de
    melhoria acionável (M9 9.2), não só um contador."""
    await asyncio.to_thread(
        rt.db.save_reaction, req.message_hash, req.reaction, req.session_id,
        req.sources, req.reason, req.question, req.answer,
    )
    return {"ok": True}


@router.get("/api/reactions/stats")
async def reaction_stats():
    """Estatísticas de reações — total, taxa positiva, fontes mais negativas."""
    return await asyncio.to_thread(rt.db.reaction_stats)


@router.get("/api/reactions/negative")
async def negative_feedback(limit: int = 20):
    """Os 👎 recentes COM o 'por quê' — o que o Leo achou ruim e por quê (M9 9.2)."""
    items = await asyncio.to_thread(rt.db.negative_feedback, limit)
    return {"count": len(items), "items": items}


@router.get("/api/benchmark/diff")
async def benchmark_diff():
    """Compara os dois últimos runs: delta de score e latência por pergunta."""
    if len(_benchmark_history) < 2:
        return {"ok": False, "error": "São necessários pelo menos 2 runs para comparar"}
    return {"ok": True, **diff_runs(_benchmark_history[-2], _benchmark_history[-1])}
