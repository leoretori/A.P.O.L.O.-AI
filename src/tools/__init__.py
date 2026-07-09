"""Ferramentas de agência do A.P.O.L.O. (M6). Importar este pacote registra as
ferramentas embutidas no registry. Ferramentas de leitura do mundo (arquivos,
agenda, e-mail) chegam nos Épicos 6.2/6.3 e exigem consentimento por escopo.
"""
from datetime import datetime

from src.tools.registry import (
    SCOPES, Tool, ToolContext, all_tools, get, register, run_tool,
)

__all__ = ["SCOPES", "Tool", "ToolContext", "register", "get",
           "all_tools", "run_tool"]


# ── Ferramentas embutidas seguras (scope "" = sem permissão) ──
def _clock(args: dict) -> dict:
    """Relógio/data local — read-only, sem tocar o mundo. Prova o framework e
    responde 'que horas são?'."""
    now = datetime.now()
    return {
        "iso": now.isoformat(timespec="seconds"),
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": ["segunda", "terça", "quarta", "quinta", "sexta",
                    "sábado", "domingo"][now.weekday()],
    }


register(Tool(name="clock", scope="", description="Hora e data locais",
              handler=_clock))


# ── Ferramentas de leitura do mundo (exigem consentimento por escopo) ──
# Importar registra as ferramentas: files.* (6.2), calendar.*/email.* (6.3).
from src.tools import files          # noqa: E402,F401  files.search / files.read
from src.tools import calendar_read  # noqa: E402,F401  calendar.events
from src.tools import email_read     # noqa: E402,F401  email.recent

# ── Ações que MODIFICAM o mundo (M10) — preview + confirmação + undo ──
from src.tools import files_write    # noqa: E402,F401  ação files.write

# ── Automação web em sandbox (M10 10.3) — read-only, allowlist de domínios ──
from src.tools import browser        # noqa: E402,F401  tool browser.run
