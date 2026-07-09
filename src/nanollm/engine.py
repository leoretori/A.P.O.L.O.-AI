"""NanoEngine — o Apolo-Nano servindo o app (Épico 3.2).

Carrega o checkpoint UMA vez (lazy, na primeira geração) e serializa as
gerações com um lock: os módulos do modelo guardam caches internos (ativação
e K/V), então o motor não é reentrante — uma geração por vez, por design.
A 600 tok/s com KV cache, uma completion de 60 tokens custa ~0,1s.

Env:
    NANO_CKPT — pasta do checkpoint (padrão data/nanollm/ckpt_v1)
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import numpy as np


class NanoEngine:
    def __init__(self, ckpt_dir: str | Path | None = None) -> None:
        self.ckpt_dir = Path(ckpt_dir or os.getenv("NANO_CKPT", "data/nanollm/ckpt_v1"))
        self._model = None
        self._tok = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------- estado
    def available(self) -> bool:
        """Existe checkpoint no disco? (não implica carregado)"""
        return (self.ckpt_dir / "model_best.npz").exists() or \
               (self.ckpt_dir / "model.npz").exists()

    def is_ready(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is None:
            from src.nanollm.generate import load_model_and_tokenizer

            self._model, self._tok = load_model_and_tokenizer(self.ckpt_dir)

    def info(self) -> dict:
        out: dict = {"available": self.available(), "ready": self.is_ready(),
                     "ckpt": str(self.ckpt_dir)}
        if self._model is not None:
            out["params_m"] = round(self._model.num_params / 1e6, 3)
            out["vocab_size"] = self._model.config.vocab_size
            out["block_size"] = self._model.config.block_size
        report = self.ckpt_dir / "eval_report.json"
        if report.exists():
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
                out["val_ppl"] = data.get("val", {}).get("ppl")
                out["passo_treino"] = data.get("passo_treino")
            except (json.JSONDecodeError, OSError):
                pass
        return out

    # ------------------------------------------------------------ geração
    def complete(self, prompt: str, max_tokens: int = 60, temperature: float = 0.8,
                 top_k: int = 40, seed: int | None = None) -> dict:
        """Completa `prompt`. Thread-safe (serializado); lazy-load na 1ª vez."""
        if not self.available():
            raise FileNotFoundError(f"sem checkpoint em {self.ckpt_dir}")
        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("prompt vazio")
        max_tokens = max(1, min(int(max_tokens), 400))
        t0 = time.time()
        with self._lock:
            self._ensure_loaded()
            model, tok = self._model, self._tok
            ids = tok.encode(prompt)
            idx = np.array([ids], dtype=np.int64)
            out = model.generate_fast(
                idx, max_tokens, temperature=float(temperature), top_k=int(top_k),
                rng=np.random.default_rng(seed), stop_id=tok.sep_id,
            )
        new = [int(t) for t in out[0, len(ids):] if int(t) != tok.sep_id]
        return {
            "text": tok.decode(new),
            "tokens": len(new),
            "ms": int((time.time() - t0) * 1000),
            "params_m": round(model.num_params / 1e6, 3),
        }
