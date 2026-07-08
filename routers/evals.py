"""Harness de avaliação (M9): roda a suíte canário e serve o placar histórico.

POST /api/evals/run     → executa a suíte, persiste e devolve o placar
GET  /api/evals/history → runs recentes + tendência ('estou melhorando?')

A correção mora em src/evals.py (determinística). Aqui fica só o RUNNER de
produção — que dispara o LLM (chat/coder/trap) e o recall (memory) — e a
persistência. O runner de LLM pega o `llm_lock` do learner: é o terceiro
consumidor do Ollama e NÃO pode voltar a rodar 14b+3b concorrente (o freeze).
"""
import asyncio
import contextlib
from datetime import datetime

from fastapi import APIRouter

from src import evals
from src import runtime as rt

router = APIRouter()


def _recall_text(prompt: str, limit: int = 4) -> str:
    """Junta título+conteúdo das fontes recuperadas para a tarefa de `recall`."""
    from routers.verify import _recall_sources
    sources = _recall_sources(prompt, limit)
    return " ".join(f"{s.get('title', '')} {s.get('content', '')}" for s in sources).strip()


@contextlib.asynccontextmanager
async def _llm_serialized():
    """Serializa contra o learner (se ativo) via o lock dele — evita o thrash de
    dois modelos inferindo juntos numa máquina CPU-only."""
    lock = getattr(rt.learner, "llm_lock", None) if rt.learner is not None else None
    if lock is not None:
        async with lock:
            yield
    else:
        yield


def _make_runner():
    """Runner de produção: async, despacha por tipo de tarefa. Injetável no teste."""
    from src.llm import KEEP_ALIVE, chat_resilient

    async def runner(task: dict) -> str:
        if task.get("kind") == "recall":
            return await asyncio.to_thread(_recall_text, task["prompt"])
        model = (rt.get_chat_model() if callable(getattr(rt, "get_chat_model", None))
                 else rt.model)
        if not model:
            return ""
        # Cede a vez ao usuário e serializa com o learner antes de inferir.
        if rt.gpu_gate is not None:
            with contextlib.suppress(Exception):
                await rt.gpu_gate.wait_for_idle(timeout=30.0)
        async with _llm_serialized():
            return await asyncio.to_thread(
                chat_resilient, model,
                [{"role": "user", "content": task["prompt"]}],
                keep_alive=KEEP_ALIVE, options={"num_predict": 350},
            ) or ""

    return runner


@router.post("/api/evals/run")
async def evals_run():
    """Executa a suíte canário (chat/coder/recall/trap), persiste e devolve o placar
    — incluindo a TAXA DE ALUCINAÇÃO (armadilhas mordidas). CUSTO: ~6 inferências."""
    run = await evals.run_canary(_make_runner())
    run["timestamp"] = datetime.now().isoformat()
    with contextlib.suppress(Exception):
        run["saved_id"] = await asyncio.to_thread(rt.db.save_eval_run, run)
    return run


@router.get("/api/evals/history")
async def evals_history(limit: int = 30):
    """Runs recentes + tendência (nota sobe / alucinação desce = melhorando)."""
    history, trend = await asyncio.gather(
        asyncio.to_thread(rt.db.get_eval_history, limit),
        asyncio.to_thread(rt.db.eval_trend),
    )
    return {"runs": len(history), "history": history, "trend": trend}


@router.get("/api/improving")
async def improving():
    """Painel 'Estou melhorando?' (M9 9.3): funde as tendências de eval, satisfação
    (👍/👎) e acerto do Coder num veredito, com o placar canário mais recente e a
    série de notas para o gráfico. Fecha o DoD do M9 (e do M7: alucinação medida)."""
    eval_trend, feedback_trend, coder_stats, latest, history = await asyncio.gather(
        asyncio.to_thread(rt.db.eval_trend),
        asyncio.to_thread(rt.db.feedback_trend),
        asyncio.to_thread(rt.db.get_coder_stats),
        asyncio.to_thread(rt.db.latest_eval),
        asyncio.to_thread(rt.db.get_eval_history, 20),
    )
    report = evals.improvement_report(eval_trend, feedback_trend, coder_stats)
    # série cronológica (antigo→recente) de nota e alucinação para o sparkline
    series = [{"score": r["score"], "hallucination_rate": r["hallucination_rate"],
               "ran_at": r["ran_at"]} for r in reversed(history)]
    return {"report": report, "latest": latest, "series": series,
            "eval_trend": eval_trend, "feedback_trend": feedback_trend,
            "coder_stats": coder_stats}
