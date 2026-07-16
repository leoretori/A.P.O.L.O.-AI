"""Sweep de scaling-law compute-matched (P1.2 do PLANO_7_PILARES.md).

O experimento 'medium' (M6.1, `docs/APOLO_NANO_ROADMAP.md`) treinou presets
diferentes com o MESMO número de passos, ignorando que cada preset tem
batch_size/block_size diferentes — logo tokens-por-passo diferentes. O
preset maior viu MENOS tokens no total e regrediu por undertraining, não por
ser estruturalmente pior. Isso não é uma curva de escala, é um viés.

Este sweep corrige a comparação: para cada preset, o número de passos é
derivado de um orçamento de TOKENS-POR-PARÂMETRO constante
(tokens_alvo = k · params), não de um número de passos fixo. Um preset com
o dobro dos parâmetros treina por (aproximadamente) o dobro dos tokens —
compute-matched no sentido de "todos veem uma quantidade de dado proporcional
ao que têm capacidade de absorver", não em FLOPs exatos.

Uso:
    python -m src.nanollm.sweep --data data/nanollm --out data/nanollm/sweep \
        --presets nano,mini,small --tokens-per-param 15
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from src.nanollm.model import GPT, GPTConfig
from src.nanollm.train import PRESETS
from src.nanollm.train import train as run_train


def _preset_params(preset_name: str, vocab_size: int) -> int:
    """Conta os parâmetros do preset sem treinar nada (só instancia e mede)."""
    p = PRESETS[preset_name]
    cfg = GPTConfig(vocab_size=vocab_size, block_size=p["block_size"], n_layer=p["n_layer"],
                    n_head=p["n_head"], n_embd=p["n_embd"], seed=0)
    return GPT(cfg).num_params


def steps_for_budget(params: int, batch_size: int, block_size: int,
                     tokens_per_param: float, min_steps: int = 20) -> int:
    """passos = tokens_alvo / tokens_por_passo, tokens_alvo = k · params."""
    tokens_target = tokens_per_param * params
    steps = int(tokens_target / (batch_size * block_size))
    return max(steps, min_steps)


def run_sweep(
    data_dir: str | Path,
    out_dir: str | Path,
    presets: list[str],
    tokens_per_param: float = 15.0,
    batch_size_override: int | None = None,
    lr: float = 6e-4,
    warmup_frac: float = 0.1,
    eval_iters: int = 10,
    seed: int = 1337,
    verbose: bool = True,
) -> dict:
    """Treina cada preset com passos derivados do orçamento tokens-por-parâmetro
    e devolve uma tabela params × passos × tokens_vistos × ppl. Nunca decide
    sozinho qual preset "vence" — só mede; a decisão é de quem lê o relatório."""
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))

    rows = []
    for name in presets:
        preset = PRESETS[name]
        batch_size = batch_size_override or preset["batch_size"]
        params = _preset_params(name, meta["vocab_size"])
        steps = steps_for_budget(params, batch_size, preset["block_size"], tokens_per_param)
        warmup = max(int(steps * warmup_frac), 1)
        preset_out = out_dir / name

        args = argparse.Namespace(
            data=str(data_dir), out=str(preset_out), preset=name, steps=steps,
            batch_size=batch_size, lr=lr, warmup=warmup, weight_decay=0.01,
            grad_clip=1.0, log_every=max(steps // 10, 1), eval_every=max(steps // 5, 1),
            eval_iters=eval_iters, seed=seed, resume=False, init_from=None,
        )
        t0 = time.time()
        result = run_train(args)
        elapsed = time.time() - t0

        val_loss = result["best_val"]
        ppl = float(np.exp(min(val_loss, 50)))
        tokens_seen = steps * batch_size * preset["block_size"]
        row = {
            "preset": name, "params": params, "steps": steps,
            "tokens_seen": tokens_seen,
            "tokens_per_param_real": round(tokens_seen / params, 2),
            "val_loss": round(val_loss, 4), "ppl": round(ppl, 2),
            "seconds": round(elapsed, 1),
        }
        rows.append(row)
        if verbose:
            print(f"{name}: {params / 1e6:.2f}M params | {steps} passos | "
                  f"{tokens_seen:,} tokens vistos | val {val_loss:.4f} | "
                  f"ppl {ppl:.2f} | {elapsed:.1f}s", flush=True)

    report = {"tokens_per_param_budget": tokens_per_param, "corpus_tokens": meta["tokens"],
              "rows": rows}
    (out_dir / "sweep_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Sweep de scaling-law compute-matched do Apolo-Nano")
    ap.add_argument("--data", default="data/nanollm", help="pasta com train.npy/meta.json")
    ap.add_argument("--out", default="data/nanollm/sweep", help="pasta de saída do sweep")
    ap.add_argument("--presets", default="nano,mini,small",
                    help="presets a comparar, separados por vírgula")
    ap.add_argument("--tokens-per-param", type=float, default=15.0,
                    help="orçamento de tokens vistos por parâmetro (k)")
    ap.add_argument("--batch-size", type=int, default=0, help="0 = usar o do preset")
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--eval-iters", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()
    report = run_sweep(
        args.data, args.out, args.presets.split(","), args.tokens_per_param,
        batch_size_override=args.batch_size or None, lr=args.lr,
        eval_iters=args.eval_iters, seed=args.seed,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
