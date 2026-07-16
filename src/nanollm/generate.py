"""Geração de texto com um checkpoint do Apolo-Nano.

Uso:
    python -m src.nanollm.generate --ckpt data/nanollm/ckpt \
        --prompt "O Apolo é" --tokens 120 --temperature 0.8
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from src.nanollm.model import GPT
from src.nanollm.tokenizer import ByteBPETokenizer


def load_model_and_tokenizer(ckpt_dir: str | Path) -> tuple[GPT, ByteBPETokenizer]:
    ckpt = Path(ckpt_dir)
    model_file = ckpt / "model_best.npz"
    if not model_file.exists():
        model_file = ckpt / "model.npz"
    model = GPT.load(model_file)
    tok = ByteBPETokenizer.load(ckpt / "tokenizer.json")
    return model, tok


def generate_text(
    model: GPT,
    tok: ByteBPETokenizer,
    prompt: str,
    max_new_tokens: int = 120,
    temperature: float = 0.8,
    top_k: int = 40,
    seed: int | None = None,
) -> str:
    ids = tok.encode(prompt) or [tok.sep_id]
    idx = np.array([ids], dtype=np.int64)
    rng = np.random.default_rng(seed)
    out = model.generate_fast(
        idx, max_new_tokens, temperature=temperature, top_k=top_k, rng=rng,
        stop_id=tok.sep_id,
    )
    new_ids = [int(i) for i in out[0, len(ids):] if int(i) != tok.sep_id]
    return prompt + tok.decode(new_ids)


def main() -> None:
    ap = argparse.ArgumentParser(description="Gera texto com o Apolo-Nano")
    ap.add_argument("--ckpt", default="data/nanollm/ckpt")
    ap.add_argument("--prompt", default="")
    ap.add_argument("--tokens", type=int, default=120)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=40)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    model, tok = load_model_and_tokenizer(args.ckpt)
    print(f"[{model.num_params / 1e6:.2f}M params, vocab {model.config.vocab_size}]")
    text = generate_text(model, tok, args.prompt, args.tokens,
                         args.temperature, args.top_k, args.seed)
    print(text)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
