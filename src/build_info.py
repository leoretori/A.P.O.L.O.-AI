"""Metadados de build/execução para o /api/health (Épico 1.3 / observabilidade).

Expõe versão do app, tempo de atividade (uptime) e o commit git em execução —
para saber, a qualquer momento, QUAL código está rodando e há quanto tempo.
"""

import os
import subprocess
import time
from functools import lru_cache

# Versão semântica do A.P.O.L.O. Sem release automatizado ainda; bump manual.
# 1.0.0 — Ano 1 do roadmap Jarvis completo (M1–M12), 2026-07-09.
APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

# Marco de início do processo — capturado no import (boot do app).
_STARTED_AT = time.time()


@lru_cache(maxsize=1)
def git_sha() -> str:
    """Commit curto em execução. Preferência: env GIT_SHA (útil em container onde
    o .git não existe) → senão `git rev-parse`. 'unknown' se indisponível."""
    env = os.getenv("GIT_SHA", "").strip()
    if env:
        return env[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


def uptime_seconds() -> int:
    return int(time.time() - _STARTED_AT)


def _human_uptime(secs: int) -> str:
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m or not parts: parts.append(f"{m}m")
    return " ".join(parts)


def build_info() -> dict:
    up = uptime_seconds()
    return {
        "version": APP_VERSION,
        "git_sha": git_sha(),
        "uptime_seconds": up,
        "uptime_human": _human_uptime(up),
    }
