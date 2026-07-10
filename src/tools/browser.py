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


def _tool_browser_interact(args: dict, ctx) -> dict:
    """Executa uma receita INTERATIVA (M20, clique/preenchimento) na sandbox.
    Passos de EFEITO (submeter) só rodam com `confirm_effects` — nunca um clique
    cego. Usa o Playwright (🔒 opt-in); erro claro se não estiver instalado."""
    allowed = webtask.parse_domains(getattr(ctx, "note", ""))
    if not allowed:
        raise PermissionError(
            "nenhum domínio autorizado — abra 🔐 Permissões, autorize 'browser.interact' "
            "e informe os domínios em que o A.P.O.L.O. pode interagir")
    steps = (args or {}).get("steps") or []
    confirm = bool((args or {}).get("confirm_effects"))
    driver_factory = (args or {}).get("_driver")   # injeção nos testes
    driver = driver_factory() if driver_factory else webtask.PlaywrightDriver()
    try:
        return webtask.run_interactive(steps, driver, allowed, confirm_effects=confirm)
    finally:
        close = getattr(driver, "close", None)
        if callable(close):
            close()


register(Tool(name="browser.interact", scope="browser.interact",
              description="Interage na web (clicar/preencher/enviar) nos domínios autorizados, com confirmação dos passos que mudam algo",
              handler=_tool_browser_interact))
