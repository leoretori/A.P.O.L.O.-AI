"""Ferramenta de automação web em sandbox (M10, Épico 10.3).

Roda uma receita de `src/webtask.py` pelo caminho seguro do M6 (`run_tool` →
consentimento por escopo `browser.control` + auditoria). A allowlist de DOMÍNIOS
vem da `note` do grant — o grant abre a capacidade, a note delimita ONDE. Só GET
(read-only): não modifica nada.
"""
from __future__ import annotations

from src import webtask
from src.tools.registry import Tool, register


def _tool_browser_run(args: dict, ctx) -> dict:
    """Executa a receita web dentro da sandbox de domínios (ctx.note)."""
    allowed = webtask.parse_domains(getattr(ctx, "note", ""))
    if not allowed:
        raise PermissionError(
            "nenhum domínio autorizado — abra 🔐 Permissões, autorize 'browser.control' "
            "e informe os domínios que o A.P.O.L.O. pode automatizar")
    steps = (args or {}).get("steps") or []
    return webtask.run(steps, webtask.HttpDriver(), allowed)


register(Tool(name="browser.run", scope="browser.control",
              description="Executa uma tarefa web (abrir/extrair/seguir link) nos domínios autorizados",
              handler=_tool_browser_run))
