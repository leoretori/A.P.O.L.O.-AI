"""Embeddings locais e soberanos (M11, Épico 11.1).

O recall do A.P.O.L.O. (RAG/ChromaDB) já roda com embeddings LOCAIS — o default
`all-MiniLM-L6-v2` (ONNX, na CPU) ou o Ollama (`nomic-embed-text`). Nenhuma API
externa. Este módulo fecha a última milha da soberania:

  1. Um FALLBACK 100% Python (`HashingEmbeddingFunction`) — sem ONNX, sem Ollama,
     sem baixar modelo, sem internet. Feature hashing de n-gramas: fraco, mas REAL
     (textos parecidos ficam mais próximos que textos diferentes). Garante que o
     recall funcione mesmo com a internet desligada e nada instalado.
  2. `backend_info()` — reporta QUAL backend está ativo e se é local, para o painel
     Saúde provar a soberania.

Determinístico e testável (mesmo texto → mesmo vetor; `hashlib`, não o `hash()`
salgado por processo). A qualidade PT-BR melhor (modelo maior) segue 🔒 HW.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata

DEFAULT_DIMS = 256


def _norm(text: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower())
                if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _features(text: str):
    """Palavras (≥3 chars) + tri-gramas de caractere — captura raiz/afinidade
    lexical mesmo em palavras que o modelo nunca viu."""
    t = _norm(text)
    words = [w for w in re.findall(r"[a-z0-9]+", t) if len(w) >= 3]
    grams = [t[i:i + 3] for i in range(len(t) - 2)] if len(t) >= 3 else []
    return words + grams


def _bucket(feature: str, dims: int) -> tuple[int, float]:
    """Feature hashing com sinal: índice do balde + sinal (±1) por bits do hash —
    o sinal reduz o viés de colisão (features diferentes não só se somam)."""
    h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "big") % dims
    sign = 1.0 if (h[4] & 1) else -1.0
    return idx, sign


def hashing_embedding(text: str, dims: int = DEFAULT_DIMS) -> list[float]:
    """Texto → vetor denso de `dims` dimensões, L2-normalizado. Determinístico e
    offline. Vetor zero (texto vazio) é retornado como está."""
    vec = [0.0] * dims
    for feat in _features(text):
        idx, sign = _bucket(feat, dims)
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine(a: list[float], b: list[float]) -> float:
    """Similaridade de cosseno entre dois vetores (assume mesma dimensão)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return round(dot, 6)     # vetores já normalizados → dot = cosseno


class HashingEmbeddingFunction:
    """Embedding function compatível com ChromaDB (opt-in via EMBED_MODEL=hashing).
    100% local/offline — o piso de soberania quando não há ONNX nem Ollama."""
    def __init__(self, dims: int = DEFAULT_DIMS):
        self.dims = dims

    def __call__(self, input):        # ChromaDB chama com uma lista de textos
        return [hashing_embedding(t, self.dims) for t in input]

    def name(self) -> str:            # ChromaDB >=0.5 exige name()
        return "apolo-hashing"


def backend_info(embed_model: str | None) -> dict:
    """Descreve o backend de embedding ATIVO e se é local (para o painel Saúde)."""
    if embed_model == "hashing":
        return {"backend": "hashing", "model": "apolo-hashing", "local": True,
                "offline_ready": True, "dims": DEFAULT_DIMS,
                "note": "fallback 100% Python — offline, sem dependências"}
    if embed_model:
        return {"backend": "ollama", "model": embed_model, "local": True,
                "offline_ready": True,
                "note": f"embeddings locais via Ollama ({embed_model})"}
    return {"backend": "onnx-minilm", "model": "all-MiniLM-L6-v2", "local": True,
            "offline_ready": True,
            "note": "default do ChromaDB, roda na CPU (ONNX); baixa o modelo 1x e cacheia"}
