"""Otimizador Adam + agenda de learning rate + clip de gradiente — do zero."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from src.nanollm.layers import Param


def clip_grad_norm(params: list[Param], max_norm: float) -> float:
    """Clipa a norma GLOBAL dos gradientes. Retorna a norma pré-clip."""
    total = math.sqrt(sum(float((p.grad * p.grad).sum()) for p in params))
    if max_norm > 0 and total > max_norm:
        scale = max_norm / (total + 1e-12)
        for p in params:
            p.grad *= scale
    return total


def lr_schedule(step: int, *, max_lr: float, min_lr: float, warmup: int, total: int) -> float:
    """Warmup linear até max_lr, depois decaimento cosseno até min_lr."""
    if step < warmup:
        return max_lr * (step + 1) / max(warmup, 1)
    if step >= total:
        return min_lr
    progress = (step - warmup) / max(total - warmup, 1)
    return min_lr + 0.5 * (max_lr - min_lr) * (1.0 + math.cos(math.pi * progress))


class Adam:
    def __init__(
        self,
        params: list[Param],
        lr: float = 3e-4,
        betas: tuple[float, float] = (0.9, 0.95),
        eps: float = 1e-8,
        weight_decay: float = 0.0,
    ) -> None:
        self.params = params
        self.lr = lr
        self.b1, self.b2 = betas
        self.eps = eps
        self.weight_decay = weight_decay
        self.t = 0
        self.m = {p.name: np.zeros_like(p.data) for p in params}
        self.v = {p.name: np.zeros_like(p.data) for p in params}

    def step(self, lr: float | None = None) -> None:
        lr = self.lr if lr is None else lr
        self.t += 1
        bc1 = 1.0 - self.b1**self.t
        bc2 = 1.0 - self.b2**self.t
        for p in self.params:
            m = self.m[p.name]
            v = self.v[p.name]
            m *= self.b1
            m += (1.0 - self.b1) * p.grad
            v *= self.b2
            v += (1.0 - self.b2) * (p.grad * p.grad)
            update = (m / bc1) / (np.sqrt(v / bc2) + self.eps)
            if self.weight_decay > 0 and p.data.ndim >= 2:  # decay só em matrizes
                update = update + self.weight_decay * p.data
            p.data -= lr * update

    # ------------------------------------------------------- persistência
    def save(self, path: str | Path) -> None:
        arrays: dict[str, np.ndarray] = {"__t__": np.array([self.t])}
        for name, arr in self.m.items():
            arrays[f"m::{name}"] = arr
        for name, arr in self.v.items():
            arrays[f"v::{name}"] = arr
        np.savez_compressed(path, **arrays)

    def load(self, path: str | Path) -> None:
        with np.load(path) as data:
            self.t = int(data["__t__"][0])
            for p in self.params:
                self.m[p.name][...] = data[f"m::{p.name}"]
                self.v[p.name][...] = data[f"v::{p.name}"]
