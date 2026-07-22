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

# Amostragem do Nano (E13) — capacidade nova, DESLIGADA por padrão, porque a
# medição não sustentou ligá-la. No ckpt_v1 vivo, 16 mensagens reais × 5 seeds
# (n=80): top_p=0.95 melhora a FORMA do título (67,5% → 76,2% passam em
# `title_ok`), mas a RELEVÂNCIA fica em ~0-2% em qualquer configuração — o teto
# aqui é escala do modelo, não amostragem — e o `gate_accept`, que é quem
# decide promoção, não melhorou. Regra do projeto: nada entra sem medição a
# favor. Os botões existem e são por chamada/env para experimentar (e o
# `repeat_penalty` já tem o escopo certo: só os tokens GERADOS).
NANO_REPEAT_PENALTY = float(os.getenv("NANO_REPEAT_PENALTY", 1.0))
NANO_TOP_P = float(os.getenv("NANO_TOP_P", 0.0))


def _cut_at_stop(text: str, stop: list[str] | None) -> tuple[str, str | None]:
    """Corta o texto na primeira stop-string encontrada. Devolve (texto, qual).

    O corte é no TEXTO (não em ids): as stops são strings do produto
    ("Pergunta:", "\\nTópico:") e o BPE não garante que virem um token só."""
    if not stop:
        return text, None
    corte, qual = len(text), None
    for s in stop:
        if not s:
            continue
        i = text.find(s)
        if 0 <= i < corte:
            corte, qual = i, s
    return (text[:corte], qual) if qual else (text, None)


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

    def reload(self) -> None:
        """Esquece os pesos em memória — a próxima geração recarrega do disco.
        Usado após o flywheel promover um checkpoint novo (M25.3): o cérebro
        recém-treinado passa a servir sem reiniciar o app."""
        with self._lock:
            self._model = None
            self._tok = None

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
                 top_k: int = 40, seed: int | None = None, *,
                 top_p: float = NANO_TOP_P, repeat_penalty: float = NANO_REPEAT_PENALTY,
                 stop: list[str] | None = None) -> dict:
        """Completa `prompt`. Thread-safe (serializado); lazy-load na 1ª vez.

        Prompt maior que a janela do modelo é atendido pelos tokens FINAIS (o
        começo não é visto) — e a resposta diz isso em `truncated` /
        `prompt_tokens_used`, em vez de devolver texto vazio calado (E2/E20).

        `repeat_penalty`/`top_p`/`stop` combatem o modo de falha nº 1 de modelo
        pequeno: degenerar em loop (E13). Os padrões vêm de env
        (`NANO_REPEAT_PENALTY`, `NANO_TOP_P`) — o motor llama.cpp já tinha isso
        e o Nano, que é MENOR e degenera mais, não tinha nada."""
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
                top_p=float(top_p), repeat_penalty=float(repeat_penalty),
            )
            usados = model.prompt_tokens_used(len(ids))
        new = [int(t) for t in out[0, len(ids):] if int(t) != tok.sep_id]
        texto, cortou = _cut_at_stop(tok.decode(new), stop)
        return {
            "text": texto,
            "tokens": len(new),
            "stopped_at": cortou,
            "ms": int((time.time() - t0) * 1000),
            "params_m": round(model.num_params / 1e6, 3),
            "prompt_tokens": len(ids),
            "prompt_tokens_used": usados,
            "truncated": usados < len(ids),
            "context_limit": model.context_limit(),
        }
