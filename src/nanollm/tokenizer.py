"""Tokenizer BPE byte-level escrito do zero (Python puro, sem libs).

Treina merges sobre bytes UTF-8: qualquer texto (acentos, emoji, código) é
representável sem <unk>. Os merges nunca cruzam fronteira de "chunk"
(palavra + espaço à esquerda), o que acelera o treino e melhora a
generalização — mesma ideia do GPT-2, com um pré-split bem mais simples.

O treino usa contagem incremental de pares (índice par→palavras afetadas),
então só as palavras que contêm o par mesclado são reprocessadas a cada
merge — viável em Python puro para amostras de alguns MB.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger("apolo.nano.tokenizer")

# Palavra com (no máximo um) espaço à esquerda, ou sobra de whitespace.
_CHUNK_RE = re.compile(r" ?\S+|\s+")

SEP_TOKEN = "<|sep|>"  # separador de documentos no corpus


def _merge_seq(seq: list[int], pair: tuple[int, int], new_id: int) -> list[int]:
    """Substitui toda ocorrência adjacente de `pair` por `new_id`."""
    out: list[int] = []
    i, n = 0, len(seq)
    a, b = pair
    while i < n:
        if i < n - 1 and seq[i] == a and seq[i + 1] == b:
            out.append(new_id)
            i += 2
        else:
            out.append(seq[i])
            i += 1
    return out


class ByteBPETokenizer:
    """BPE byte-level: ids 0-255 são bytes crus; merges criam ids novos."""

    def __init__(self) -> None:
        self.merges: list[tuple[int, int]] = []  # ordem = rank
        self.ranks: dict[tuple[int, int], int] = {}  # par -> id resultante
        self.special: dict[str, int] = {}
        self._vocab_bytes: dict[int, bytes] = {}
        self._cache: dict[str, list[int]] = {}

    # ------------------------------------------------------------- treino
    def train(self, text: str, vocab_size: int = 4096, *, verbose: bool = False) -> None:
        """Aprende merges a partir de `text` até atingir `vocab_size`.

        vocab final = 256 bytes + merges + especiais (SEP).
        """
        n_special = 1  # SEP
        n_merges = vocab_size - 256 - n_special
        if n_merges < 0:
            raise ValueError("vocab_size precisa ser >= 257")

        freqs = Counter(_CHUNK_RE.findall(text))
        words: dict[str, list[int]] = {w: list(w.encode("utf-8")) for w in freqs}

        pair_counts: Counter[tuple[int, int]] = Counter()
        pair_words: dict[tuple[int, int], set[str]] = defaultdict(set)
        for w, seq in words.items():
            f = freqs[w]
            for pair in zip(seq, seq[1:]):
                pair_counts[pair] += f
                pair_words[pair].add(w)

        self.merges = []
        next_id = 256
        while len(self.merges) < n_merges and pair_counts:
            # max determinístico: maior contagem, desempate pelo par menor
            best = max(pair_counts.items(), key=lambda kv: (kv[1], (-kv[0][0], -kv[0][1])))
            pair, count = best
            if count < 2:
                break
            for w in list(pair_words.get(pair, ())):
                seq = words[w]
                f = freqs[w]
                for p in zip(seq, seq[1:]):
                    pair_counts[p] -= f
                    if pair_counts[p] <= 0:
                        del pair_counts[p]
                    pair_words[p].discard(w)
                seq = _merge_seq(seq, pair, next_id)
                words[w] = seq
                for p in zip(seq, seq[1:]):
                    pair_counts[p] += f
                    pair_words[p].add(w)
            self.merges.append(pair)
            if verbose and len(self.merges) % 500 == 0:
                print(f"  merges: {len(self.merges)}/{n_merges}")
            next_id += 1

        self._finalize()

    def _finalize(self) -> None:
        """Reconstrói ranks, vocab de bytes e especiais a partir de merges."""
        self.ranks = {pair: 256 + i for i, pair in enumerate(self.merges)}
        vocab = {i: bytes([i]) for i in range(256)}
        for i, (a, b) in enumerate(self.merges):
            vocab[256 + i] = vocab[a] + vocab[b]
        sep_id = 256 + len(self.merges)
        self.special = {SEP_TOKEN: sep_id}
        vocab[sep_id] = SEP_TOKEN.encode("utf-8")
        self._vocab_bytes = vocab
        self._cache = {}

    # ---------------------------------------------------------- interface
    @property
    def vocab_size(self) -> int:
        return 256 + len(self.merges) + len(self.special)

    @property
    def sep_id(self) -> int:
        return self.special[SEP_TOKEN]

    def encode(self, text: str) -> list[int]:
        """Texto → lista de ids (não interpreta tokens especiais no texto)."""
        ids: list[int] = []
        for chunk in _CHUNK_RE.findall(text):
            cached = self._cache.get(chunk)
            if cached is None:
                cached = self._encode_chunk(list(chunk.encode("utf-8")))
                if len(self._cache) < 200_000:
                    self._cache[chunk] = cached
            ids.extend(cached)
        return ids

    def _encode_chunk(self, seq: list[int]) -> list[int]:
        while len(seq) >= 2:
            pairs = set(zip(seq, seq[1:]))
            best = min(pairs, key=lambda p: self.ranks.get(p, 1 << 30))
            if best not in self.ranks:
                break
            seq = _merge_seq(seq, best, self.ranks[best])
        return seq

    def decode(self, ids: list[int]) -> str:
        """ids → texto. Id fora do vocabulário vira nada (robusto por escolha),
        mas AVISA no log: sem isso, um bug de vocab (modelo e tokenizer
        dessincronizados, por exemplo) viraria só um texto "encolhido", sem
        nenhum sinal de que algo estava errado (E25)."""
        pedacos = []
        desconhecidos = 0
        for i in ids:
            b = self._vocab_bytes.get(int(i))
            if b is None:
                desconhecidos += 1
                continue
            pedacos.append(b)
        if desconhecidos:
            logger.warning(
                f"[tokenizer] decode ignorou {desconhecidos}/{len(ids)} id(s) fora do "
                f"vocabulário (tamanho {self.vocab_size}) — modelo e tokenizer podem "
                f"estar dessincronizados")
        return b"".join(pedacos).decode("utf-8", errors="replace")

    # ------------------------------------------------------- persistência
    def save(self, path: str | Path) -> None:
        payload = {
            "version": 1,
            "type": "byte-bpe",
            "merges": [list(p) for p in self.merges],
            "special": self.special,
        }
        Path(path).write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ByteBPETokenizer":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        tok = cls()
        tok.merges = [tuple(p) for p in payload["merges"]]
        tok._finalize()
        # sanity: especiais salvos devem bater com os reconstruídos
        if payload.get("special") and payload["special"] != tok.special:
            tok.special = {k: int(v) for k, v in payload["special"].items()}
        return tok
