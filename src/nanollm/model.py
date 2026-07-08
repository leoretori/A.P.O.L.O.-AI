"""GPT decoder-only em NumPy puro — forward, loss e backward manuais.

Arquitetura GPT-2-like: embeddings de token+posição, blocos pré-LN com
atenção causal multi-head e MLP GELU, LayerNorm final e cabeça de linguagem.
Sem autograd: GPT.backward() propaga gradientes na ordem reversa exata do
forward. Checkpoints são .npz (NumPy) + config JSON embutida.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from src.nanollm.layers import Block, Embedding, LayerNorm, Linear, Module, Param, softmax


@dataclass
class GPTConfig:
    vocab_size: int = 4096
    block_size: int = 256  # contexto máximo (tokens)
    n_layer: int = 6
    n_head: int = 8
    n_embd: int = 256
    dtype: str = "float32"  # float64 p/ checagem numérica de gradiente
    seed: int = 1337


class GPT(Module):
    def __init__(self, config: GPTConfig) -> None:
        self.config = config
        c = config
        rng = np.random.default_rng(c.seed)
        self.wte = Embedding("wte", c.vocab_size, c.n_embd, rng, dtype=c.dtype)
        self.wpe = Param("wpe.w", rng.normal(0.0, 0.02, (c.block_size, c.n_embd)).astype(c.dtype))
        self.blocks = [
            Block(f"h{i}", c.n_embd, c.n_head, c.n_layer, rng, dtype=c.dtype)
            for i in range(c.n_layer)
        ]
        self.ln_f = LayerNorm("ln_f", c.n_embd, dtype=c.dtype)
        self.lm_head = Linear("lm_head", c.n_embd, c.vocab_size, rng, dtype=c.dtype)
        # caches p/ backward
        self._probs: np.ndarray | None = None
        self._targets: np.ndarray | None = None
        self._t: int = 0

    # ------------------------------------------------------------- params
    def params(self) -> list[Param]:
        out = self.wte.params() + [self.wpe]
        for b in self.blocks:
            out += b.params()
        return out + self.ln_f.params() + self.lm_head.params()

    @property
    def num_params(self) -> int:
        return sum(p.data.size for p in self.params())

    # ------------------------------------------------------------ forward
    def forward(
        self, idx: np.ndarray, targets: np.ndarray | None = None
    ) -> tuple[np.ndarray, float | None]:
        """idx (B,T) int → logits (B,T,V); com targets (B,T) calcula a loss."""
        _, t = idx.shape
        if t > self.config.block_size:
            raise ValueError(f"sequência {t} > block_size {self.config.block_size}")
        self._t = t
        x = self.wte.forward(idx) + self.wpe.data[:t]
        for block in self.blocks:
            x = block.forward(x)
        x = self.ln_f.forward(x)
        logits = self.lm_head.forward(x)

        loss = None
        if targets is not None:
            m = logits.max(axis=-1, keepdims=True)
            z = logits - m
            lse = np.log(np.exp(z).sum(axis=-1, keepdims=True))
            logp = z - lse
            b_idx, t_idx = np.indices(targets.shape)
            loss = float(-logp[b_idx, t_idx, targets].mean())
            self._probs = np.exp(logp)
            self._targets = targets
        return logits, loss

    # ----------------------------------------------------------- backward
    def backward(self) -> None:
        """Backprop da última forward COM targets. Acumula em Param.grad."""
        if self._probs is None:
            raise RuntimeError("backward() exige forward(idx, targets) antes")
        probs, targets = self._probs, self._targets
        n = targets.size
        dlogits = probs.copy()
        b_idx, t_idx = np.indices(targets.shape)
        dlogits[b_idx, t_idx, targets] -= 1.0
        dlogits /= n

        dx = self.lm_head.backward(dlogits)
        dx = self.ln_f.backward(dx)
        for block in reversed(self.blocks):
            dx = block.backward(dx)
        self.wpe.grad[: self._t] += dx.sum(axis=0)
        self.wte.backward(dx)
        self._probs = None
        self._targets = None

    # ----------------------------------------------------------- geração
    def generate(
        self,
        idx: np.ndarray,
        max_new_tokens: int,
        temperature: float = 0.8,
        top_k: int = 40,
        rng: np.random.Generator | None = None,
        stop_id: int | None = None,
    ) -> np.ndarray:
        """Amostragem autoregressiva. idx (B,T) → (B, T+n)."""
        rng = rng or np.random.default_rng()
        for _ in range(max_new_tokens):
            ctx = idx[:, -self.config.block_size :]
            logits, _ = self.forward(ctx)
            logits = logits[:, -1, :] / max(temperature, 1e-6)
            if top_k and top_k < logits.shape[-1]:
                kth = np.partition(logits, -top_k, axis=-1)[:, [-top_k]]
                logits = np.where(logits < kth, -np.inf, logits)
            probs = softmax(logits)
            nxt = np.array(
                [rng.choice(probs.shape[-1], p=row) for row in probs], dtype=idx.dtype
            )[:, None]
            idx = np.concatenate([idx, nxt], axis=1)
            if stop_id is not None and bool((nxt == stop_id).all()):
                break
        return idx

    # ------------------------------------------------------- persistência
    def save(self, path: str | Path) -> None:
        arrays = {p.name: p.data for p in self.params()}
        arrays["__config__"] = np.frombuffer(
            json.dumps(asdict(self.config)).encode("utf-8"), dtype=np.uint8
        )
        np.savez_compressed(path, **arrays)

    @classmethod
    def load(cls, path: str | Path) -> "GPT":
        with np.load(path) as data:
            cfg_json = bytes(data["__config__"]).decode("utf-8")
            config = GPTConfig(**json.loads(cfg_json))
            model = cls(config)
            for p in model.params():
                p.data[...] = data[p.name]
        return model
