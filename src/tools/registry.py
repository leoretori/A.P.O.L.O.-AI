"""Framework de ferramentas de agência com permissão (M6, Épico 6.1).

Toda ação que toca o mundo é uma `Tool` com um `scope` de permissão. O `run_tool`
é o ÚNICO caminho para executá-las e sempre: (1) checa o consentimento do usuário
para o escopo; (2) registra a invocação no log de auditoria; (3) só então roda —
ou nega. Ferramentas seguras (leitura local trivial, ex.: relógio) têm scope ""
e não exigem permissão.

Escopos declarados em SCOPES aparecem na tela de consentimento mesmo antes de
haver uma ferramenta que os use (o usuário pode autorizar previamente).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("apolo.tools")

# Catálogo de escopos de permissão (o que o A.P.O.L.O. PODE pedir para acessar).
SCOPES: dict[str, str] = {
    "files.read": "Ler arquivos das pastas que você autorizar",
    "calendar.read": "Ler sua agenda (somente leitura)",
    "email.read": "Ler seus e-mails (somente leitura)",
}


@dataclass
class Tool:
    name: str
    scope: str                       # "" = seguro, sem permissão especial
    description: str
    handler: Callable[[dict], dict]


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> None:
    _REGISTRY[tool.name] = tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def all_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def _summarize(obj) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s[:400]


def run_tool(name: str, args: dict | None, db=None) -> dict:
    """Executa uma ferramenta pelo caminho seguro: consentimento → auditoria →
    execução (ou negação). `db` fornece is_permission_granted/log_tool."""
    tool = get(name)
    if not tool:
        return {"ok": False, "error": f"ferramenta desconhecida: {name}"}

    granted = (not tool.scope) or (db is not None and db.is_permission_granted(tool.scope))
    result = None
    error = None
    if granted:
        try:
            result = tool.handler(args or {})
        except Exception as e:
            error = str(e)[:300]
            logger.warning(f"[tool] {name} falhou: {e}")

    # Auditoria SEMPRE (permitida ou negada) — a agência é inspecionável.
    if db is not None:
        try:
            db.log_tool(name, tool.scope, granted,
                        _summarize(args or {}),
                        _summarize(error or result))
        except Exception as e:
            logger.debug(f"[tool] audit falhou: {e}")

    if not granted:
        return {"ok": False, "denied": True, "scope": tool.scope,
                "error": f"permissão '{tool.scope}' não concedida",
                "scope_label": SCOPES.get(tool.scope, tool.scope)}
    if error is not None:
        return {"ok": False, "error": error}
    return {"ok": True, "result": result}
