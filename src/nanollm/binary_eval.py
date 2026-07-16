"""Avaliação do portão binário (M27/P1.3): acurácia no held-out val, não só
"treinou sem erro". `build_binary_dataset` já separa train/val por um split
determinístico (seed fixa) DENTRO de `_write_tokenized` — este módulo
reproduz o MESMO split a partir de `pairs.jsonl` (escrito na mesma ordem dos
`examples` tokenizados) para saber quais pares foram held-out, e então mede
`nano_binary_classify` de verdade neles.

Uso:
    python -m src.nanollm.binary_eval \
        --ckpt data/nanollm/ckpt_binary_backend_apis \
        --dataset data/nanollm/tasks/binary_backend_apis
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_held_out(
    dataset_dir: str | Path, val_fraction: float = 0.15, seed: int = 42
) -> tuple[str, list[tuple[str, str]]]:
    """(pergunta, [(contexto, resposta_esperada), ...]) — só o split de VAL,
    reproduzido com a MESMA rng/seed que `taskdata._write_tokenized` usou."""
    out = Path(dataset_dir)
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    lines = (out / "pairs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    examples = [json.loads(line) for line in lines]

    rng = np.random.default_rng(seed)
    order = rng.permutation(len(examples))
    n_val = max(int(len(examples) * val_fraction), 1)
    val_idx = set(order[:n_val].tolist())

    held_out = [(examples[i]["context"], examples[i]["answer"])
                for i in range(len(examples)) if i in val_idx]
    return meta["question"], held_out


def evaluate_binary_gate(
    engine, question: str, pairs: list[tuple[str, str]], seed: int | None = None
) -> dict:
    """Roda `nano_binary_classify` de verdade em cada par held-out e mede
    acurácia E taxa de decisão separadamente — um portão que sempre recusa
    (`None`) tem acurácia indefinida, não deve parecer "bom" por omissão."""
    from src.nanollm.tasks import nano_binary_classify

    n = len(pairs)
    acertos = recusas = 0
    for context, expected in pairs:
        expected_bool = expected == "sim"
        got = nano_binary_classify(engine, context, question, seed=seed)
        if got is None:
            recusas += 1
        elif got == expected_bool:
            acertos += 1
    decididos = n - recusas
    return {
        "n": n,
        "acertos": acertos,
        "recusas": recusas,
        "decididos": decididos,
        "acuracia_geral": round(acertos / n, 4) if n else 0.0,
        "acuracia_quando_decide": round(acertos / decididos, 4) if decididos else None,
        "taxa_decisao": round(decididos / n, 4) if n else 0.0,
    }


def main() -> None:
    import sys

    from src.nanollm.engine import NanoEngine

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    ap = argparse.ArgumentParser(description="Avalia o portão binário no held-out val")
    ap.add_argument("--ckpt", required=True, help="checkpoint treinado (model_best.npz)")
    ap.add_argument("--dataset", required=True, help="pasta do dataset (taskdata --task binary)")
    ap.add_argument("--val-fraction", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    question, pairs = load_held_out(args.dataset, args.val_fraction, args.seed)
    engine = NanoEngine(ckpt_dir=args.ckpt)
    result = evaluate_binary_gate(engine, question, pairs)
    result["question"] = question
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
