"""Amostragem de qualidade real do aprendizado (P2.5).

`storage_learning.get_summary_quality()` só mede FORMA (tem cabeçalho "##" ou
não) — não diz se o conteúdo é preciso, útil ou específico. Este módulo roda
um juiz LLM sobre uma amostra ALEATÓRIA de resumos já salvos e registra o
resultado num placar histórico (mesmo padrão do `blind_eval`, P1.4): sem
conjunto fixo aqui (a amostra É aleatória de propósito — mede a base inteira
ao longo do tempo, não um ponto fixo de comparação), mas com o mesmo
princípio de nunca inflar o número e sempre registrar de verdade.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from src.factcheck import QUALITY_PROMPT, parse_quality_verdict

logger = logging.getLogger("apolo.learning.quality")


def run_quality_sample(db, judge_fn: Callable[[str, str], str], n: int = 15) -> dict:
    """Amostra `n` tópicos salvos e pede ao juiz precisão/utilidade/especificidade
    de cada um. `judge_fn(topic, summary) -> texto da resposta` é injetável
    (fake nos testes; `make_llm_quality_judge` liga o motor de verdade)."""
    rows = db.sample_topics_for_quality(n)
    if not rows:
        return {"status": "skipped", "reason": "sem tópicos com resumo no banco"}

    results = []
    for r in rows:
        try:
            verdict = parse_quality_verdict(judge_fn(r["topic"], r["summary"]))
        except Exception as e:
            logger.debug(f"[quality] juiz falhou em '{r['topic'][:40]}': {e}")
            verdict = None
        results.append({"id": r["id"], "topic": r["topic"], "passed": verdict})

    decided = [r for r in results if r["passed"] is not None]
    passed = sum(1 for r in decided if r["passed"])
    pass_rate = round(100 * passed / len(decided), 1) if decided else None
    return {
        "status": "ok", "n": len(results), "decided": len(decided),
        "passed": passed, "pass_rate": pass_rate, "results": results,
    }


def make_llm_quality_judge(model: str | None = None, *, temperature: float = 0.0):
    """Juiz real usando o motor próprio. Import preguiçoso (sem LLM nos testes) —
    mesmo padrão do `blind_eval.make_llm_judge`."""
    from src.providers import get_provider

    prov = get_provider()
    if model is None:
        try:
            from src import runtime
            model = runtime.get_chat_model()
        except Exception:
            model = None
        if not model:
            models = prov.list_models()
            model = models[0] if models else "apolo"

    def judge_fn(topic: str, summary: str) -> str:
        try:
            from src import runtime as rt
            if rt.gpu_gate:
                rt.gpu_gate.wait_for_idle_sync()
        except Exception:
            pass
        prompt = QUALITY_PROMPT.format(topic=topic, summary=summary[:1200])
        return prov.complete(model, [{"role": "user", "content": prompt}],
                             options={"temperature": temperature, "num_predict": 4})

    return judge_fn


# ── Placar histórico (src.jsonl_history, extraído no P2.6) ────────
def append_quality_history(path: str | Path, result: dict) -> None:
    """1 linha JSONL por rodada — append-only, nunca reescreve o passado.
    Só registra rodadas com resultado real (`status=ok`)."""
    if result.get("status") != "ok":
        return
    from src.jsonl_history import append_entry
    append_entry(path, {
        "n": result["n"], "decided": result["decided"],
        "passed": result["passed"], "pass_rate": result["pass_rate"],
    })


def read_quality_history(path: str | Path, limit: int = 50) -> list[dict]:
    """Lê o placar histórico, mais recente por último (ordem de gravação)."""
    from src.jsonl_history import read_entries
    return read_entries(path, limit)


def run_tracked_quality_sample(db, judge_fn: Callable[[str, str], str], *,
                               history_path: str | Path, n: int = 15) -> dict:
    """`run_quality_sample` + registro no placar histórico numa chamada só."""
    result = run_quality_sample(db, judge_fn, n)
    append_quality_history(history_path, result)
    return result
