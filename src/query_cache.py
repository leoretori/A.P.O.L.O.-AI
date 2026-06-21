"""Cache de consultas RAG e FTS — evita re-buscar o mesmo tópico no mesmo turno.

Problema: cada mensagem do chat faz:
  1. rag.recall(query, N)  — N embeddings + busca vetorial no ChromaDB
  2. knowledge_db.format_context(query) — FTS no Supabase/SQLite

Se o usuário faz perguntas relacionadas (ex.: "o que é asyncio?" → "como uso asyncio?")
o contexto recuperado é idêntico ou muito similar. Este cache guarda resultados
por (query normalizada) com TTL curto para que mudanças no índice apareçam logo.

Integrado em app.py — as funções _do_recall() e _do_fts() consultam aqui primeiro.
"""

import re
import time
from typing import Any

_TTL_RECALL = 90.0   # segundos — recall muda quando novos tópicos são indexados
_TTL_FTS    = 60.0   # FTS muda com mais frequência (inserts do learner)

# Dois dicts separados para não misturar tipos de resultado
_recall_cache: dict[str, tuple[float, Any]] = {}  # key → (expires_at, value)
_fts_cache:    dict[str, tuple[float, Any]] = {}


def _normalize(query: str) -> str:
    """Normaliza a query para chave de cache — case-insensitive, sem pontuação."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", query.lower())).strip()[:120]


# ── Recall RAG ────────────────────────────────────────────────────────────────

def recall_get(query: str) -> list | None:
    key = _normalize(query)
    entry = _recall_cache.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    _recall_cache.pop(key, None)
    return None


def recall_put(query: str, value: list) -> list:
    key = _normalize(query)
    _recall_cache[key] = (time.monotonic() + _TTL_RECALL, value)
    # Limpa entradas expiradas ocasionalmente (evita crescimento ilimitado)
    if len(_recall_cache) > 200:
        now = time.monotonic()
        for k in list(_recall_cache):
            if _recall_cache[k][0] < now:
                del _recall_cache[k]
    return value


# ── FTS Knowledge ─────────────────────────────────────────────────────────────

def fts_get(query: str) -> str | None:
    key = _normalize(query)
    entry = _fts_cache.get(key)
    if entry and time.monotonic() < entry[0]:
        return entry[1]
    _fts_cache.pop(key, None)
    return None


def fts_put(query: str, value: str) -> str:
    key = _normalize(query)
    _fts_cache[key] = (time.monotonic() + _TTL_FTS, value)
    if len(_fts_cache) > 100:
        now = time.monotonic()
        for k in list(_fts_cache):
            if _fts_cache[k][0] < now:
                del _fts_cache[k]
    return value


def invalidate_all() -> None:
    """Limpa ambos os caches — chamado quando novos dados são indexados."""
    _recall_cache.clear()
    _fts_cache.clear()


def stats() -> dict:
    now = time.monotonic()
    alive_r = sum(1 for e in _recall_cache.values() if e[0] > now)
    alive_f = sum(1 for e in _fts_cache.values() if e[0] > now)
    return {"recall_entries": alive_r, "fts_entries": alive_f}
