"""Ferramentas de agência do A.P.O.L.O. (M6). Importar este pacote registra as
ferramentas embutidas no registry. Ferramentas de leitura do mundo (arquivos,
agenda, e-mail) chegam nos Épicos 6.2/6.3 e exigem consentimento por escopo.
"""
from datetime import datetime

from src.tools.registry import (
    SCOPES, Tool, all_tools, get, register, run_tool,
)

__all__ = ["SCOPES", "Tool", "register", "get", "all_tools", "run_tool"]


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
