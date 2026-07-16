"""Quantização int8 de checkpoint para inferência (M5.2 do roadmap do Nano).

Escopo deliberadamente pequeno: só os pesos GRANDES (matrizes 2D — embeddings
e projeções lineares, que dominam o tamanho do checkpoint) viram int8. Bias e
ganho/deslocamento de LayerNorm (1D, já minúsculos) seguem float32 — quantizá-
los não reduz tamanho de forma relevante e só acrescentaria ruído.

Escala por COLUNA (um fator por saída/dimensão, não um único fator pro tensor
inteiro): cada coluna tem sua própria amplitude, e usar um fator só encolheria
demais as colunas de amplitude pequena. Simétrica (sem zero-point) — os pesos
já são ~N(0, 0.02), centrados em zero.
"""

from __future__ import annotations

import numpy as np

_INT8_MAX = 127


def quantize_int8(w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Quantiza uma matriz 2D (n_in, n_out) para int8, com 1 escala por COLUNA
    (eixo -1). Retorna (q int8, scale float32 de shape (n_out,))."""
    amax = np.abs(w).max(axis=0)
    scale = (amax / _INT8_MAX).astype(np.float32)
    scale = np.where(scale == 0, np.float32(1.0), scale)  # coluna nula → escala neutra
    q = np.clip(np.round(w / scale), -_INT8_MAX, _INT8_MAX).astype(np.int8)
    return q, scale


def dequantize_int8(q: np.ndarray, scale: np.ndarray) -> np.ndarray:
    """Inverso de `quantize_int8`: int8 + escala por coluna → float32."""
    return (q.astype(np.float32) * scale).astype(np.float32)


def main() -> None:
    """CLI: `python -m src.nanollm.quantize --ckpt <pasta>` — quantiza o
    checkpoint (model_best.npz ou model.npz) da pasta e grava model_q.npz ao
    lado, junto de um relatório antes/depois (tamanho + ppl, se houver val.npy
    na pasta de dados). `GPT.load` lê o resultado sem mudança nenhuma."""
    import argparse
    import json as _json
    from pathlib import Path

    from src.nanollm.model import GPT

    ap = argparse.ArgumentParser(description="Quantiza um checkpoint do Apolo-Nano p/ int8")
    ap.add_argument("--ckpt", required=True, help="pasta do checkpoint (model_best.npz/model.npz)")
    ap.add_argument("--data", default=None, help="pasta com val.npy p/ medir degradação de ppl")
    args = ap.parse_args()

    ckpt = Path(args.ckpt)
    model_file = ckpt / "model_best.npz"
    if not model_file.exists():
        model_file = ckpt / "model.npz"
    model = GPT.load(model_file)
    out_file = ckpt / "model_q.npz"
    info = model.save_quantized(out_file)

    report: dict = {
        "params_m": round(model.num_params / 1e6, 3),
        "quantized_tensors": info["quantized"],
        "size_full_kb": round(model_file.stat().st_size / 1024, 1),
        "size_quantized_kb": round(out_file.stat().st_size / 1024, 1),
    }
    if args.data:
        from src.nanollm.data import load_tokens
        from src.nanollm.eval import perplexity

        val_path = Path(args.data) / "val.npy"
        if val_path.exists():
            tokens = load_tokens(val_path)
            model_q = GPT.load(out_file)
            report["ppl_full"] = perplexity(model, tokens)["ppl"]
            report["ppl_quantized"] = perplexity(model_q, tokens)["ppl"]

    print(_json.dumps(report, indent=2, ensure_ascii=False))
    print(f"✓ gravado {out_file}")


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
