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
from src.nanollm.quantize import dequantize_int8, quantize_int8

# Teto de contexto do caminho rápido para modelos ALiBi (posição relativa: a
# matemática não impede passar do block_size de treino — o que limita é a
# memória do KV cache, O(n_layer · T · n_embd)).
ALIBI_GEN_CONTEXT = 1024


@dataclass
class GPTConfig:
    vocab_size: int = 4096
    block_size: int = 256  # contexto máximo (tokens) — só limita treino/máscara no ALiBi
    n_layer: int = 6
    n_head: int = 8
    n_embd: int = 256
    dtype: str = "float32"  # float64 p/ checagem numérica de gradiente
    seed: int = 1337
    # "learned": embedding de posição absoluta (padrão, o de sempre).
    # "alibi": viés relativo SEM parâmetro na atenção (Press et al.) — sem
    # tabela de posição, então o mesmo checkpoint funciona em qualquer T,
    # inclusive T > block_size de treino (P1.5 do PLANO_7_PILARES.md).
    pos_encoding: str = "learned"
    # Weight tying (E15): a cabeça de saída REUSA a matriz de embedding
    # (lm_head.w = wte.wᵀ). No v1 de 3,39M, `wte` e `lm_head.w` eram 1,05M cada
    # — um terço dos parâmetros duplicado. GPT-2, Pythia e SmolLM amarram os
    # dois. Default False para NÃO reinterpretar checkpoints antigos (que têm
    # as duas matrizes de verdade); `load()` detecta pelo arquivo, e o treino
    # novo liga por padrão (`--tie-weights`).
    tie_weights: bool = False


class GPT(Module):
    def __init__(self, config: GPTConfig) -> None:
        self.config = config
        c = config
        assert c.pos_encoding in ("learned", "alibi"), f"pos_encoding inválido: {c.pos_encoding}"
        use_alibi = c.pos_encoding == "alibi"
        rng = np.random.default_rng(c.seed)
        self.wte = Embedding("wte", c.vocab_size, c.n_embd, rng, dtype=c.dtype)
        self.wpe = (None if use_alibi else
                    Param("wpe.w", rng.normal(0.0, 0.02, (c.block_size, c.n_embd)).astype(c.dtype)))
        self.blocks = [
            Block(f"h{i}", c.n_embd, c.n_head, c.n_layer, rng, dtype=c.dtype, use_alibi=use_alibi)
            for i in range(c.n_layer)
        ]
        self.ln_f = LayerNorm("ln_f", c.n_embd, dtype=c.dtype)
        self.lm_head = Linear("lm_head", c.n_embd, c.vocab_size, rng, dtype=c.dtype)
        # E15: com tying, a matriz da cabeça é uma VISTA transposta de `wte` —
        # os dois papéis leem o MESMO buffer, e o Adam atualiza in-place
        # (`p.data -= …`), então a vista nunca desanda. `params()` devolve o
        # peso uma vez só (senão levaria dois updates por passo) e o `backward`
        # soma o gradiente do papel de saída no de embedding.
        self.tie_weights = bool(getattr(c, "tie_weights", False))
        if self.tie_weights:
            self.lm_head.w.data = self.wte.w.data.T
        # caches p/ backward
        self._probs: np.ndarray | None = None
        self._targets: np.ndarray | None = None
        self._t: int = 0

    # ------------------------------------------------------------- params
    def params(self) -> list[Param]:
        out = self.wte.params() + ([self.wpe] if self.wpe is not None else [])
        for b in self.blocks:
            out += b.params()
        head = [p for p in self.lm_head.params()
                if not (self.tie_weights and p is self.lm_head.w)]
        return out + self.ln_f.params() + head

    @property
    def num_params(self) -> int:
        return sum(p.data.size for p in self.params())

    # ------------------------------------------------------------ forward
    def forward(
        self, idx: np.ndarray, targets: np.ndarray | None = None
    ) -> tuple[np.ndarray, float | None]:
        """idx (B,T) int → logits (B,T,V); com targets (B,T) calcula a loss."""
        _, t = idx.shape
        if self.wpe is not None and t > self.config.block_size:
            raise ValueError(f"sequência {t} > block_size {self.config.block_size}")
        self._t = t
        x = self.wte.forward(idx)
        if self.wpe is not None:
            x = x + self.wpe.data[:t]
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
        if self.tie_weights:
            # o MESMO peso serviu como embedding e como cabeça: o gradiente dos
            # dois papéis soma (é o que torna o tying correto, não só barato).
            self.wte.w.grad += self.lm_head.w.grad.T
            self.lm_head.w.grad[...] = 0.0
        dx = self.ln_f.backward(dx)
        for block in reversed(self.blocks):
            dx = block.backward(dx)
        if self.wpe is not None:
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
        top_p: float = 0.0,
        repeat_penalty: float = 1.0,
        repeat_window: int = 64,
    ) -> np.ndarray:
        """Amostragem autoregressiva. idx (B,T) → (B, T+n)."""
        rng = rng or np.random.default_rng()
        n_prompt = idx.shape[1]
        for _ in range(max_new_tokens):
            ctx = idx if self.wpe is None else idx[:, -self.config.block_size :]
            logits, _ = self.forward(ctx)
            gerados = idx[:, n_prompt:][:, -repeat_window:]
            nxt = self._sample(logits[:, -1, :], temperature, top_k, rng, idx.dtype,
                               top_p=top_p, repeat_penalty=repeat_penalty,
                               recent=gerados)
            idx = np.concatenate([idx, nxt], axis=1)
            if stop_id is not None and bool((nxt == stop_id).all()):
                break
        return idx

    # ------------------------------------- geração incremental (KV cache)
    def _prefill(self, idx: np.ndarray) -> np.ndarray:
        """Forward completo do prompt guardando K/V por camada → logits."""
        _, t = idx.shape
        x = self.wte.forward(idx)
        if self.wpe is not None:
            x = x + self.wpe.data[:t]
        for block in self.blocks:
            x = block.forward(x, keep_kv=True)
        return self.lm_head.forward(self.ln_f.forward(x))

    def _step(self, token: np.ndarray, pos: int) -> np.ndarray:
        """Um token novo (B,1) na posição `pos` → logits (B,1,V), via cache."""
        x = self.wte.forward(token)
        if self.wpe is not None:
            x = x + self.wpe.data[pos : pos + 1]
        for block in self.blocks:
            x = block.step(x)
        return self.lm_head.forward(self.ln_f.forward(x))

    def context_limit(self, max_context: int | None = None) -> int:
        """Tokens que cabem na janela do caminho rápido (prompt + gerados).

        - posição APRENDIDA (`wpe`): teto rígido = `block_size`, o tamanho da
          tabela de posições.
        - **ALiBi**: o viés é relativo, então o cache pode passar do
          `block_size` de treino (é a razão de existir do ALiBi — o caminho
          lento já extrapolava, o rápido truncava igual ao learned, E11). O
          teto vira memória, não matemática: `ALIBI_GEN_CONTEXT` por padrão.
        """
        if max_context is not None:
            return max(2, int(max_context))
        if self.wpe is not None:
            return self.config.block_size
        return max(self.config.block_size, ALIBI_GEN_CONTEXT)

    def prompt_tokens_used(self, n_prompt: int, max_context: int | None = None) -> int:
        """Quantos tokens do prompt o modelo REALMENTE vê (o resto é cortado
        pela janela). Serve para o chamador reportar truncagem em vez de
        devolver texto vazio sem avisar (E2/E20)."""
        limit = self.context_limit(max_context)
        return min(int(n_prompt), limit - 1)

    def generate_fast(
        self,
        idx: np.ndarray,
        max_new_tokens: int,
        temperature: float = 0.8,
        top_k: int = 40,
        rng: np.random.Generator | None = None,
        stop_id: int | None = None,
        max_context: int | None = None,
        top_p: float = 0.0,
        repeat_penalty: float = 1.0,
        repeat_window: int = 64,
    ) -> np.ndarray:
        """Igual a generate(), mas O(T) por token via KV cache.

        Devolve **o prompt ORIGINAL inteiro + os tokens gerados** — mesmo
        quando a janela corta o começo do prompt. Antes, o prompt era truncado
        e o array devolvido ficava MENOR que o prompt do chamador; quem fatiava
        `out[0, len(ids):]` (engine, generate.py) recebia lista vazia, sem erro
        e sem aviso: qualquer prompt acima de ~block_size tokens gerava texto
        `''` silenciosamente (E2).

        Ao encher a janela, o cache não para mais a geração: re-prefila com a
        metade recente e segue (janela deslizante de verdade — custo O(T) uma
        vez a cada `limit/2` tokens).
        """
        rng = rng or np.random.default_rng()
        limit = self.context_limit(max_context)
        prompt = idx
        window = idx[:, -(limit - 1):] if idx.shape[1] > limit - 1 else idx
        gerados: list[np.ndarray] = []

        logits = self._prefill(window)
        for _ in range(max_new_tokens):
            recent = (np.concatenate(gerados[-repeat_window:], axis=1)
                      if gerados else None)     # só o que ESTE modelo gerou
            nxt = self._sample(logits[:, -1, :], temperature, top_k, rng, window.dtype,
                               top_p=top_p, repeat_penalty=repeat_penalty,
                               recent=recent)
            window = np.concatenate([window, nxt], axis=1)
            gerados.append(nxt)
            if stop_id is not None and bool((nxt == stop_id).all()):
                break
            if window.shape[1] >= limit:
                window = window[:, -(limit // 2):]   # desliza a janela…
                logits = self._prefill(window)       # …e reconstrói o cache
            else:
                logits = self._step(nxt, pos=window.shape[1] - 1)
        if not gerados:
            return prompt
        return np.concatenate([prompt, *gerados], axis=1)

    @staticmethod
    def _sample(logits: np.ndarray, temperature: float, top_k: int,
                rng: np.random.Generator, dtype, *,
                top_p: float = 0.0, repeat_penalty: float = 1.0,
                recent: np.ndarray | None = None) -> np.ndarray:
        """Amostra o próximo token (B,1).

        Além de temperatura + top-k, o modo de falha nº 1 de modelo pequeno
        (E13): degenerar em loop. Contramedidas, na ordem do llama.cpp —
        1. **repeat_penalty**: logit de token já emitido em `recent` é dividido
           por `repeat_penalty` se positivo, multiplicado se negativo (assim
           penaliza nos dois sinais). `recent` são os tokens GERADOS, nunca os
           do prompt: as tarefas do Nano completam um padrão que precisa REUSAR
           palavras do prompt (é literalmente o que `title_relevant` exige) —
           medido no ckpt vivo, penalizar o prompt derrubou o gate_accept;
        2. **top_p** (nucleus): mantém só o menor conjunto de tokens cuja massa
           acumulada chega a `top_p` — corta a cauda longa de lixo;
        3. **top_k** como já era.
        """
        logits = logits.astype(np.float64, copy=True)
        if repeat_penalty and repeat_penalty != 1.0 and recent is not None and recent.size:
            for b in range(logits.shape[0]):
                ids = np.unique(recent[b]) if recent.ndim > 1 else np.unique(recent)
                ids = ids[(ids >= 0) & (ids < logits.shape[-1])]
                vals = logits[b, ids]
                logits[b, ids] = np.where(vals > 0, vals / repeat_penalty,
                                          vals * repeat_penalty)
        logits = logits / max(temperature, 1e-6)
        if top_k and top_k < logits.shape[-1]:
            kth = np.partition(logits, -top_k, axis=-1)[:, [-top_k]]
            logits = np.where(logits < kth, -np.inf, logits)
        if 0.0 < top_p < 1.0:
            probs = softmax(logits)
            ordem = np.argsort(-probs, axis=-1)
            acum = np.cumsum(np.take_along_axis(probs, ordem, axis=-1), axis=-1)
            # mantém o 1º token que cruza o limiar (nunca zera a linha inteira)
            corta = acum - np.take_along_axis(probs, ordem, axis=-1) >= top_p
            fora = np.zeros_like(corta)
            np.put_along_axis(fora, ordem, corta, axis=-1)
            logits = np.where(fora, -np.inf, logits)
        probs = softmax(logits)
        return np.array(
            [rng.choice(probs.shape[-1], p=row) for row in probs], dtype=dtype
        )[:, None]

    # ------------------------------------------------------- persistência
    def save(self, path: str | Path) -> None:
        arrays = {p.name: p.data for p in self.params()}
        arrays["__config__"] = np.frombuffer(
            json.dumps(asdict(self.config)).encode("utf-8"), dtype=np.uint8
        )
        np.savez_compressed(path, **arrays)

    def save_quantized(self, path: str | Path) -> dict:
        """Checkpoint p/ INFERÊNCIA (M5.2): as matrizes 2D (embeddings/lineares —
        a maior parte do tamanho) viram int8 + escala por coluna; bias/LayerNorm
        (1D, já pequenos) seguem float32. `load()` dequantiza sozinho — quem lê
        não precisa saber que o arquivo era quantizado. Só para servir; treinar
        a partir daqui perderia precisão do gradiente."""
        arrays: dict = {}
        n_quantized = 0
        for p in self.params():
            if p.data.ndim == 2:
                q, scale = quantize_int8(p.data)
                arrays[f"{p.name}.q8"] = q
                arrays[f"{p.name}.scale"] = scale
                n_quantized += 1
            else:
                arrays[p.name] = p.data
        arrays["__config__"] = np.frombuffer(
            json.dumps(asdict(self.config)).encode("utf-8"), dtype=np.uint8
        )
        np.savez_compressed(path, **arrays)
        return {"params": len(self.params()), "quantized": n_quantized}

    @classmethod
    def load(cls, path: str | Path) -> "GPT":
        with np.load(path) as data:
            cfg_json = bytes(data["__config__"]).decode("utf-8")
            config = GPTConfig(**json.loads(cfg_json))
            # Quem manda sobre o tying é o ARQUIVO, não a config: checkpoint com
            # `lm_head.w` próprio tem duas matrizes de verdade e amarrá-las
            # jogaria fora a cabeça treinada, em silêncio. Checkpoints anteriores
            # ao E15 nem têm a chave `tie_weights` na config.
            config.tie_weights = not ("lm_head.w" in data or "lm_head.w.q8" in data)
            model = cls(config)
            for p in model.params():
                qkey = f"{p.name}.q8"
                if qkey in data:
                    p.data[...] = dequantize_int8(data[qkey], data[f"{p.name}.scale"])
                else:
                    p.data[...] = data[p.name]
        return model
