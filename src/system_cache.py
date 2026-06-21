"""Cache do system prompt por sessão.

O system prompt (SYSTEM_PROMPT + perfil + contexto de projeto) é idêntico
entre mensagens da mesma sessão enquanto o perfil e o projeto não mudam.
Recomputar a cada mensagem gasta tempo de CPU e tokens.

Este módulo guarda o resultado por sessão e invalida automaticamente
quando o perfil ou o projeto muda (via hash do conteúdo).
"""

import hashlib
from dataclasses import dataclass


@dataclass
class _Entry:
    content: str
    key: str  # hash(profile_facts + project_section)


_cache: dict[str, _Entry] = {}  # session_id → Entry


def _key(profile_facts: str, project_section: str) -> str:
    return hashlib.md5(f"{profile_facts}|{project_section}".encode()).hexdigest()


def get(session_id: str, profile_facts: str, project_section: str) -> str | None:
    """Retorna o system prompt cacheado se o perfil/projeto não mudaram."""
    entry = _cache.get(session_id)
    if entry and entry.key == _key(profile_facts, project_section):
        return entry.content
    return None


def put(session_id: str, content: str, profile_facts: str, project_section: str) -> str:
    """Armazena o system prompt e retorna ele mesmo."""
    _cache[session_id] = _Entry(content=content, key=_key(profile_facts, project_section))
    return content


def invalidate(session_id: str | None = None) -> None:
    """Remove do cache — chamado quando o perfil ou projeto muda."""
    if session_id:
        _cache.pop(session_id, None)
    else:
        _cache.clear()


def stats() -> dict:
    return {"entries": len(_cache)}
