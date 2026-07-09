"""Embeddings locais (M11, Épico 11.1): visibilidade da soberania do recall.

  GET  /api/embeddings/info      → backend ativo (local? offline-ready?)
  POST /api/embeddings/selftest  → prova o fallback 100% Python: textos parecidos
                                   ficam mais próximos que diferentes, SEM internet.
"""
import os

from fastapi import APIRouter

from src import embeddings as E

router = APIRouter()


@router.get("/api/embeddings/info")
async def embeddings_info():
    model = os.getenv("EMBED_MODEL", "").strip() or None
    return E.backend_info(model)


@router.post("/api/embeddings/selftest")
async def embeddings_selftest(payload: dict | None = None):
    """Gera embeddings do fallback soberano e mostra que ele SEPARA semântica —
    roda offline, sem modelo baixado. Prova que o recall nunca depende da nuvem."""
    p = payload or {}
    a = p.get("a", "o gato subiu no telhado")
    b = p.get("b", "o gato pulou para o telhado")   # parecido com a
    c = p.get("c", "reforma tributária e juros altos")  # diferente
    va, vb, vc = (E.hashing_embedding(a), E.hashing_embedding(b), E.hashing_embedding(c))
    sim_ab = E.cosine(va, vb)
    sim_ac = E.cosine(va, vc)
    return {
        "ok": sim_ab > sim_ac,       # parecidos > diferentes = embedding funciona
        "offline": True,
        "dims": E.DEFAULT_DIMS,
        "similar_pair": {"a": a, "b": b, "cosine": sim_ab},
        "different_pair": {"a": a, "c": c, "cosine": sim_ac},
    }
