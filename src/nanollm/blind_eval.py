"""Avaliação ÀS CEGAS: o cérebro próprio (Nano) contra o professor (Qwen) — M28.

O DoD do M28 pede "medir contra o Qwen às cegas". Aqui está o juiz honesto: para
cada pergunta, geramos a resposta do Nano e a do Qwen, **embaralhamos a ordem**
(semente fixa → reprodutível) e mostramos as duas ao juiz como "A" e "B", SEM
dizer quem é quem. O juiz escolhe a melhor; só depois mapeamos de volta. Assim o
placar não pode ser enviesado por saber qual é o modelo próprio.

Núcleo determinístico: `model_a_fn`/`model_b_fn`/`judge_fn` são injetáveis (fakes
nos testes). `make_llm_judge` monta um juiz real com o motor; `run_blind_eval`
liga tudo no banco + Nano + Qwen para rodar de verdade.
"""
from __future__ import annotations

import logging
import random
import re
from typing import Callable

logger = logging.getLogger("apolo.nano.blindeval")

JUDGE_PROMPT = (
    "Você é um juiz imparcial. Para a pergunta abaixo, há duas respostas, A e B. "
    "Escolha a MELHOR (mais correta, direta e útil). Responda APENAS com a letra "
    "A ou B.\n\nPergunta: {q}\n\n[A]\n{a}\n\n[B]\n{b}\n\nMelhor (A ou B):"
)


def _parse_choice(text: str) -> str | None:
    """Extrai 'A'/'B' da resposta do juiz. Casa a letra ISOLADA (fronteira de
    palavra) — senão o 'a' de 'resposta' seria lido como voto em A."""
    m = re.search(r"\b([AB])\b", (text or "").upper())
    return m.group(1) if m else None


def blind_compare(
    prompts: list[str],
    nano_fn: Callable[[str], str],
    teacher_fn: Callable[[str], str],
    judge_fn: Callable[[str, str, str], str],
    *,
    seed: int = 0,
) -> dict:
    """Compara Nano vs professor às cegas. Retorna placar + win-rate do Nano.

    `judge_fn(pergunta, respA, respB) -> "A"|"B"` (cego: não sabe quem é quem).
    A ordem A/B é sorteada por pergunta (semente fixa) e desfeita no placar."""
    rng = random.Random(seed)
    wins = {"nano": 0, "teacher": 0, "tie": 0}
    rounds = []
    for q in prompts:
        a_nano = (nano_fn(q) or "").strip()
        a_teach = (teacher_fn(q) or "").strip()
        nano_is_A = rng.random() < 0.5           # embaralha a posição
        first, second = (a_nano, a_teach) if nano_is_A else (a_teach, a_nano)
        choice = _parse_choice(judge_fn(q, first, second))
        if choice is None:
            wins["tie"] += 1
            winner = "tie"
        else:
            picked_A = choice == "A"
            winner = "nano" if (picked_A == nano_is_A) else "teacher"
            wins[winner] += 1
        rounds.append({"q": q[:80], "winner": winner, "nano_was": "A" if nano_is_A else "B"})
    decided = wins["nano"] + wins["teacher"]
    win_rate = round(100 * wins["nano"] / decided, 1) if decided else 0.0
    return {"n": len(prompts), "wins": wins, "nano_win_rate": win_rate, "rounds": rounds}


def make_llm_judge(model: str | None = None, *, temperature: float = 0.0):
    """Juiz real usando o motor próprio (Qwen). Import preguiçoso (sem LLM nos testes)."""
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

    def judge_fn(q: str, a: str, b: str) -> str:
        prompt = JUDGE_PROMPT.format(q=q, a=a[:600], b=b[:600])
        return prov.complete(model, [{"role": "user", "content": prompt}],
                             options={"temperature": temperature, "num_predict": 4})

    return judge_fn


def run_blind_eval(db, nano_engine, *, limit: int = 30, seed: int = 0,
                   max_tokens: int = 80) -> dict:
    """Roda a avaliação às cegas de verdade: perguntas reais do banco, Nano do
    checkpoint vivo, professor + juiz no motor próprio. É o número honesto do M28
    (win-rate do Nano vs Qwen). Barato de pular se não há checkpoint/perguntas."""
    from src.nanollm.distill import make_llm_teacher

    prompts = db.first_user_messages(limit=limit)
    if not prompts:
        return {"status": "skipped", "reason": "sem perguntas no banco"}
    if nano_engine is None or not nano_engine.available():
        return {"status": "skipped", "reason": "Nano sem checkpoint treinado"}

    teacher = make_llm_teacher(max_tokens=max_tokens)

    def nano_fn(q: str) -> str:
        return nano_engine.complete(q, max_tokens=max_tokens).get("text", "")

    res = blind_compare(prompts, nano_fn, teacher, make_llm_judge(), seed=seed)
    res["status"] = "ok"
    logger.info(f"[blind_eval] Nano win-rate {res['nano_win_rate']}% em {res['n']} perguntas")
    return res


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.nanollm.blind_eval [--limit N]`. Roda o Nano do
    checkpoint vivo contra o Qwen, às cegas, e imprime o win-rate honesto."""
    import argparse

    p = argparse.ArgumentParser(description="Nano vs Qwen às cegas (M28)")
    p.add_argument("--limit", type=int, default=30, help="máx. de perguntas do banco")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args(argv)

    from src.nanollm.engine import NanoEngine
    from src.storage import DatabaseManager

    res = run_blind_eval(DatabaseManager(), NanoEngine(), limit=args.limit, seed=args.seed)
    if res.get("status") != "ok":
        print(f"pulado: {res.get('reason')}")
        return 1
    w = res["wins"]
    print(f"Nano vs Qwen (às cegas, {res['n']} perguntas): "
          f"Nano {w['nano']} · Qwen {w['teacher']} · empates {w['tie']}")
    print(f"→ win-rate do cérebro próprio: {res['nano_win_rate']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
