"""Camadas do transformer com forward E backward manuais (sem autograd).

Cada módulo guarda no forward o que o backward precisa (cache de ativação)
e ACUMULA gradientes em Param.grad — zere com zero_grad() antes de cada passo.
A corretude do backprop é provada por checagem numérica em
tests/test_nanollm_grad.py.
"""

from __future__ import annotations

import math

import numpy as np


class Param:
    """Tensor treinável + gradiente acumulado."""

    __slots__ = ("name", "data", "grad")

    def __init__(self, name: str, data: np.ndarray) -> None:
        self.name = name
        self.data = data
        self.grad = np.zeros_like(data)


class Module:
    def params(self) -> list[Param]:
        return []

    def zero_grad(self) -> None:
        for p in self.params():
            p.grad[...] = 0


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    e = np.exp(x - x.max(axis=axis, keepdims=True))
    return e / e.sum(axis=axis, keepdims=True)


# --------------------------------------------------------------------- GELU
_GELU_C = math.sqrt(2.0 / math.pi)


def gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(_GELU_C * (x + 0.044715 * x**3)))


def gelu_backward(x: np.ndarray, dy: np.ndarray) -> np.ndarray:
    t = np.tanh(_GELU_C * (x + 0.044715 * x**3))
    du = _GELU_C * (1.0 + 3 * 0.044715 * x**2)
    return dy * (0.5 * (1.0 + t) + 0.5 * x * (1.0 - t**2) * du)


# ------------------------------------------------------------------- Linear
class Linear(Module):
    def __init__(
        self,
        name: str,
        n_in: int,
        n_out: int,
        rng: np.random.Generator,
        std: float = 0.02,
        dtype: str = "float32",
    ) -> None:
        self.w = Param(f"{name}.w", rng.normal(0.0, std, (n_in, n_out)).astype(dtype))
        self.b = Param(f"{name}.b", np.zeros(n_out, dtype=dtype))
        self._x: np.ndarray | None = None

    def forward(self, x: np.ndarray) -> np.ndarray:
        self._x = x
        return x @ self.w.data + self.b.data

    def backward(self, dy: np.ndarray) -> np.ndarray:
        x = self._x
        x2 = x.reshape(-1, x.shape[-1])
        dy2 = dy.reshape(-1, dy.shape[-1])
        self.w.grad += x2.T @ dy2
        self.b.grad += dy2.sum(axis=0)
        return (dy2 @ self.w.data.T).reshape(x.shape)

    def params(self) -> list[Param]:
        return [self.w, self.b]


# ---------------------------------------------------------------- LayerNorm
class LayerNorm(Module):
    def __init__(self, name: str, dim: int, dtype: str = "float32", eps: float = 1e-5) -> None:
        self.g = Param(f"{name}.g", np.ones(dim, dtype=dtype))
        self.b = Param(f"{name}.b", np.zeros(dim, dtype=dtype))
        self.eps = eps
        self._xhat: np.ndarray | None = None
        self._inv: np.ndarray | None = None

    def forward(self, x: np.ndarray) -> np.ndarray:
        mu = x.mean(axis=-1, keepdims=True)
        xc = x - mu
        var = (xc * xc).mean(axis=-1, keepdims=True)
        inv = 1.0 / np.sqrt(var + self.eps)
        xhat = xc * inv
        self._xhat, self._inv = xhat, inv
        return self.g.data * xhat + self.b.data

    def backward(self, dy: np.ndarray) -> np.ndarray:
        xhat, inv = self._xhat, self._inv
        dim = dy.shape[-1]
        self.g.grad += (dy * xhat).reshape(-1, dim).sum(axis=0)
        self.b.grad += dy.reshape(-1, dim).sum(axis=0)
        dxhat = dy * self.g.data
        return inv * (
            dxhat
            - dxhat.mean(axis=-1, keepdims=True)
            - xhat * (dxhat * xhat).mean(axis=-1, keepdims=True)
        )

    def params(self) -> list[Param]:
        return [self.g, self.b]


# ---------------------------------------------------------------- Embedding
class Embedding(Module):
    def __init__(
        self,
        name: str,
        n_vocab: int,
        dim: int,
        rng: np.random.Generator,
        std: float = 0.02,
        dtype: str = "float32",
    ) -> None:
        self.w = Param(f"{name}.w", rng.normal(0.0, std, (n_vocab, dim)).astype(dtype))
        self._idx: np.ndarray | None = None

    def forward(self, idx: np.ndarray) -> np.ndarray:
        self._idx = idx
        return self.w.data[idx]

    def backward(self, dy: np.ndarray) -> None:
        np.add.at(self.w.grad, self._idx, dy)

    def params(self) -> list[Param]:
        return [self.w]


# ------------------------------------------------- atenção causal multi-head
class CausalSelfAttention(Module):
    def __init__(
        self,
        name: str,
        n_embd: int,
        n_head: int,
        n_layer: int,
        rng: np.random.Generator,
        dtype: str = "float32",
    ) -> None:
        assert n_embd % n_head == 0, "n_embd deve ser múltiplo de n_head"
        self.n_head = n_head
        self.qkv = Linear(f"{name}.qkv", n_embd, 3 * n_embd, rng, dtype=dtype)
        # projeção residual com init reduzida (estilo GPT-2)
        self.proj = Linear(
            f"{name}.proj", n_embd, n_embd, rng, std=0.02 / math.sqrt(2 * n_layer), dtype=dtype
        )
        self._cache: tuple | None = None
        self._tril: np.ndarray | None = None

    def _mask(self, t: int) -> np.ndarray:
        if self._tril is None or self._tril.shape[0] < t:
            self._tril = np.tril(np.ones((t, t), dtype=bool))
        return self._tril[:t, :t]

    def forward(self, x: np.ndarray) -> np.ndarray:
        bsz, t, dim = x.shape
        hd = dim // self.n_head
        qkv = self.qkv.forward(x)  # (B, T, 3D)
        qkv = qkv.reshape(bsz, t, 3, self.n_head, hd).transpose(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]  # (B, nh, T, hd)
        scale = 1.0 / math.sqrt(hd)
        scores = (q @ k.swapaxes(-1, -2)) * scale  # (B, nh, T, T)
        neg = np.asarray(-1e30, dtype=scores.dtype)
        scores = np.where(self._mask(t), scores, neg)
        probs = softmax(scores)
        y = probs @ v  # (B, nh, T, hd)
        self._cache = (q, k, v, probs, scale)
        y = y.transpose(0, 2, 1, 3).reshape(bsz, t, dim)
        return self.proj.forward(y)

    def backward(self, dy: np.ndarray) -> np.ndarray:
        q, k, v, probs, scale = self._cache
        bsz, nh, t, hd = q.shape
        dyh = self.proj.backward(dy)  # (B, T, D)
        dyh = dyh.reshape(bsz, t, nh, hd).transpose(0, 2, 1, 3)  # (B, nh, T, hd)
        dprobs = dyh @ v.swapaxes(-1, -2)  # (B, nh, T, T)
        dv = probs.swapaxes(-1, -2) @ dyh
        # backward do softmax; entradas mascaradas têm probs=0 → dscores=0
        dscores = probs * (dprobs - (dprobs * probs).sum(axis=-1, keepdims=True))
        dq = (dscores @ k) * scale
        dk = (dscores.swapaxes(-1, -2) @ q) * scale
        dqkv = np.stack([dq, dk, dv])  # (3, B, nh, T, hd)
        dqkv = dqkv.transpose(1, 3, 0, 2, 4).reshape(bsz, t, 3 * nh * hd)
        return self.qkv.backward(dqkv)

    def params(self) -> list[Param]:
        return self.qkv.params() + self.proj.params()


# ----------------------------------------------------------------------- MLP
class MLP(Module):
    def __init__(
        self,
        name: str,
        n_embd: int,
        n_layer: int,
        rng: np.random.Generator,
        dtype: str = "float32",
    ) -> None:
        self.fc = Linear(f"{name}.fc", n_embd, 4 * n_embd, rng, dtype=dtype)
        self.proj = Linear(
            f"{name}.proj", 4 * n_embd, n_embd, rng, std=0.02 / math.sqrt(2 * n_layer), dtype=dtype
        )
        self._pre: np.ndarray | None = None

    def forward(self, x: np.ndarray) -> np.ndarray:
        pre = self.fc.forward(x)
        self._pre = pre
        return self.proj.forward(gelu(pre))

    def backward(self, dy: np.ndarray) -> np.ndarray:
        dh = self.proj.backward(dy)
        return self.fc.backward(gelu_backward(self._pre, dh))

    def params(self) -> list[Param]:
        return self.fc.params() + self.proj.params()


# --------------------------------------------------------------------- Block
class Block(Module):
    """Bloco transformer pré-LN: x + attn(ln1(x)); x + mlp(ln2(x))."""

    def __init__(
        self,
        name: str,
        n_embd: int,
        n_head: int,
        n_layer: int,
        rng: np.random.Generator,
        dtype: str = "float32",
    ) -> None:
        self.ln1 = LayerNorm(f"{name}.ln1", n_embd, dtype=dtype)
        self.attn = CausalSelfAttention(f"{name}.attn", n_embd, n_head, n_layer, rng, dtype=dtype)
        self.ln2 = LayerNorm(f"{name}.ln2", n_embd, dtype=dtype)
        self.mlp = MLP(f"{name}.mlp", n_embd, n_layer, rng, dtype=dtype)

    def forward(self, x: np.ndarray) -> np.ndarray:
        x = x + self.attn.forward(self.ln1.forward(x))
        return x + self.mlp.forward(self.ln2.forward(x))

    def backward(self, dy: np.ndarray) -> np.ndarray:
        dy = dy + self.ln2.backward(self.mlp.backward(dy))
        return dy + self.ln1.backward(self.attn.backward(dy))

    def params(self) -> list[Param]:
        return self.ln1.params() + self.attn.params() + self.ln2.params() + self.mlp.params()
