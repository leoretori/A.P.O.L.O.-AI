"""Loop de treino do Apolo-Nano (CPU, NumPy puro), com resume e checkpoints.

Uso:
    python -m src.nanollm.train --data data/nanollm --out data/nanollm/ckpt \
        --preset small --steps 10000
    # retomar de onde parou:
    python -m src.nanollm.train --data data/nanollm --out data/nanollm/ckpt --resume

Presets pensados para o Ryzen 5 4600G (CPU-only, 16GB):
    nano  ~0.8M params — fumaça/depuração (minutos)
    mini  ~3M  params — primeiro modelo de verdade (horas)
    small ~7M  params — o alvo do Apolo-Nano v1 (dia+)
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from src.nanollm.data import get_batch, load_tokens
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.optim import Adam, clip_grad_norm, lr_schedule

# Escala incremental (M26): "small" (~3-6M) é o v1; "medium"/"large" sobem o teto
# no hardware atual (CPU) — treino mais lento, mas viável de madrugada com passos
# limitados. n_head sempre divide n_embd. batch cai conforme o modelo cresce p/
# caber na RAM. A meta do M26 é medir cobertura por tarefa à medida que cresce.
PRESETS: dict[str, dict] = {
    "nano": dict(n_layer=2, n_head=4, n_embd=128, block_size=128, batch_size=16),
    "mini": dict(n_layer=4, n_head=4, n_embd=192, block_size=192, batch_size=12),
    "small": dict(n_layer=6, n_head=8, n_embd=256, block_size=256, batch_size=8),
    "medium": dict(n_layer=8, n_head=8, n_embd=320, block_size=256, batch_size=6),  # ~10M
    "large": dict(n_layer=12, n_head=8, n_embd=448, block_size=256, batch_size=4),  # ~30M
}


def evaluate(model: GPT, tokens: np.ndarray, batch_size: int, iters: int,
             rng: np.random.Generator) -> float:
    losses = []
    for _ in range(iters):
        x, y = get_batch(tokens, model.config.block_size, batch_size, rng)
        _, loss = model.forward(x, y)
        model._probs = None  # descarta cache de loss (forward só de avaliação)
        model._targets = None
        losses.append(loss)
    return float(np.mean(losses))


def train(args: argparse.Namespace) -> dict:
    data_dir = Path(args.data)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    train_tokens = load_tokens(data_dir / "train.npy")
    val_path = data_dir / "val.npy"
    val_tokens = load_tokens(val_path) if val_path.exists() else None
    meta = json.loads((data_dir / "meta.json").read_text(encoding="utf-8"))

    preset = PRESETS[args.preset]
    batch_size = args.batch_size or preset["batch_size"]

    ckpt_path = out / "model.npz"
    optim_path = out / "optim.npz"
    state_path = out / "state.json"

    if args.resume and ckpt_path.exists():
        model = GPT.load(ckpt_path)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        start_step = state["step"]
        best_val = state.get("best_val", float("inf"))
        print(f"retomando do passo {start_step} (val {best_val:.4f})")
    elif args.init_from:
        # Fine-tune: parte dos PESOS de outro checkpoint, mas com run NOVO
        # (passo 0, otimizador e agenda de LR frescos, dataset de tarefa).
        src = Path(args.init_from)
        src_model = src / "model_best.npz"
        if not src_model.exists():
            src_model = src / "model.npz"
        model = GPT.load(src_model)
        if model.config.vocab_size != meta["vocab_size"]:
            raise ValueError(
                f"vocab do init ({model.config.vocab_size}) != dataset "
                f"({meta['vocab_size']}) — fine-tune exige o MESMO tokenizer")
        start_step = 0
        best_val = float("inf")
        tok_src = src / "tokenizer.json"
        if tok_src.exists():
            shutil.copy(tok_src, out / "tokenizer.json")
        print(f"fine-tune a partir de {src_model.name} "
              f"({model.num_params / 1e6:.2f}M params)")
    else:
        config = GPTConfig(
            vocab_size=meta["vocab_size"],
            block_size=preset["block_size"],
            n_layer=preset["n_layer"],
            n_head=preset["n_head"],
            n_embd=preset["n_embd"],
            seed=args.seed,
            pos_encoding=getattr(args, "pos_encoding", "learned"),
        )
        model = GPT(config)
        start_step = 0
        best_val = float("inf")
        # deixa o diretório do checkpoint auto-contido p/ geração
        tok_src = data_dir / "tokenizer.json"
        if tok_src.exists():
            shutil.copy(tok_src, out / "tokenizer.json")

    optim = Adam(model.params(), lr=args.lr, weight_decay=args.weight_decay)
    if args.resume and optim_path.exists():
        optim.load(optim_path)

    print(f"modelo: {model.num_params / 1e6:.2f}M params | "
          f"corpus: {len(train_tokens):,} tokens | batch {batch_size} | "
          f"contexto {model.config.block_size}")

    # Early-stop (item 2 do PLANO_CEREBRO_ASSUME.md): o medium (M26) rodou os
    # 15.000 passos completos e OVERFITOU nos últimos ~9.000 — o val loss
    # atingiu o mínimo no passo 6.000 e só piorou depois. `patience` (0 =
    # desligado, compatível com scripts/testes existentes) para o treino
    # depois de N avaliações seguidas SEM melhora no val — o `model_best.npz`
    # já é o que interessa; continuar só queima tempo de máquina.
    patience = getattr(args, "patience", 0)
    evals_no_improve = 0

    rng = np.random.default_rng(args.seed + start_step)
    eval_rng = np.random.default_rng(9999)
    t_last = time.time()
    stopped_early_at = None
    for step in range(start_step, args.steps):
        x, y = get_batch(train_tokens, model.config.block_size, batch_size, rng)
        model.zero_grad()
        _, loss = model.forward(x, y)
        model.backward()
        grad_norm = clip_grad_norm(model.params(), args.grad_clip)
        lr = lr_schedule(step, max_lr=args.lr, min_lr=args.lr / 10,
                         warmup=args.warmup, total=args.steps)
        optim.step(lr)

        if (step + 1) % args.log_every == 0:
            dt = time.time() - t_last
            tok_s = args.log_every * batch_size * model.config.block_size / max(dt, 1e-9)
            print(f"passo {step + 1}/{args.steps} | loss {loss:.4f} | "
                  f"lr {lr:.2e} | grad {grad_norm:.2f} | {tok_s:,.0f} tok/s", flush=True)
            t_last = time.time()

        if (step + 1) % args.eval_every == 0 or step + 1 == args.steps:
            if val_tokens is not None and len(val_tokens) > model.config.block_size + 2:
                val = evaluate(model, val_tokens, batch_size, args.eval_iters, eval_rng)
                print(f"  → val loss {val:.4f}", flush=True)
            else:
                val = loss
            model.save(ckpt_path)
            optim.save(optim_path)
            if val < best_val:
                best_val = val
                evals_no_improve = 0
                model.save(out / "model_best.npz")
            else:
                evals_no_improve += 1
            state_path.write_text(
                json.dumps({"step": step + 1, "best_val": best_val, "last_val": val}),
                encoding="utf-8",
            )
            t_last = time.time()
            if patience > 0 and evals_no_improve >= patience:
                print(f"early-stop no passo {step + 1}: val sem melhorar por "
                      f"{evals_no_improve} avaliações (patience={patience})", flush=True)
                stopped_early_at = step + 1
                break

    return {"step": stopped_early_at or args.steps, "best_val": best_val,
            "stopped_early": stopped_early_at is not None}


def main() -> None:
    ap = argparse.ArgumentParser(description="Treina o Apolo-Nano do zero")
    ap.add_argument("--data", default="data/nanollm", help="pasta com train.npy/meta.json")
    ap.add_argument("--out", default="data/nanollm/ckpt", help="pasta de checkpoints")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="small")
    ap.add_argument("--steps", type=int, default=10_000)
    ap.add_argument("--batch-size", type=int, default=0, help="0 = usar o do preset")
    ap.add_argument("--lr", type=float, default=6e-4)
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--grad-clip", type=float, default=1.0)
    ap.add_argument("--log-every", type=int, default=10)
    ap.add_argument("--eval-every", type=int, default=250)
    ap.add_argument("--eval-iters", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--pos-encoding", choices=["learned", "alibi"], default="learned",
                    help="alibi: sem tabela de posição, generaliza a contexto maior (P1.5)")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--init-from", default=None,
                    help="fine-tune: warm-start dos pesos deste checkpoint (run novo)")
    ap.add_argument("--patience", type=int, default=0,
                    help="para o treino após N avaliações sem melhora no val (0 = desliga)")
    train(ap.parse_args())


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
