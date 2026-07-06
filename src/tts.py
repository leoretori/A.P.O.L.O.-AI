"""TTS do A.P.O.L.O. — fachada que escolhe o engine de voz (M3, Épico 3.1).

Ordem de preferência (soberania primeiro):
  1. Piper  → 100% LOCAL, roda no CPU (o caminho soberano)
  2. edge-tts → nuvem da Microsoft (fallback de qualidade)
  3. browser → speechSynthesis do navegador (fallback do frontend)

`TTS_ENGINE` (env) força um engine: 'piper' | 'edge' | 'auto' (padrão).
Se o engine forçado não estiver disponível, cai para a resolução automática.

Mantém a API que o resto do app já usava (`is_available`, `synthesize`,
`VOICES`, `DEFAULT_VOICE`) e acrescenta metadados para reportar HONESTAMENTE se a
voz é local (`is_local`, `engine_info`) — fecha a mentira do L1 (o código antigo
dizia que edge-tts era "local"/"offline", e não é).
"""
import os

from src import tts_edge, tts_piper

_ENGINES = {"piper": tts_piper, "edge-tts": tts_edge}

# Compat: o nome do engine edge continua exportando os rótulos de voz padrão.
DEFAULT_VOICE = tts_edge.DEFAULT_VOICE


def active_engine() -> str:
    """Resolve o engine ativo: 'piper' | 'edge-tts' | 'browser'."""
    pref = os.getenv("TTS_ENGINE", "auto").strip().lower()
    if pref in ("piper",) and tts_piper.is_available():
        return "piper"
    if pref in ("edge", "edge-tts") and tts_edge.is_available():
        return "edge-tts"
    # auto (ou forçado indisponível): prioriza o LOCAL, depois nuvem, depois browser.
    if tts_piper.is_available():
        return "piper"
    if tts_edge.is_available():
        return "edge-tts"
    return "browser"


def _module(engine: str):
    return _ENGINES.get(engine)


def is_available() -> bool:
    """True se há um engine de servidor (Piper ou edge). 'browser' não conta —
    esse é o fallback do frontend, sem áudio do servidor."""
    return active_engine() != "browser"


def is_local() -> bool:
    """True só quando a voz é 100% local (Piper). edge-tts é nuvem."""
    return active_engine() == "piper"


def media_type() -> str:
    m = _module(active_engine())
    return getattr(m, "MEDIA_TYPE", "audio/mpeg") if m else "audio/mpeg"


def voices() -> dict:
    """Vozes do engine ativo (rótulo → id). Piper expõe via função (o modelo pode
    aparecer em runtime); edge via dict."""
    m = _module(active_engine())
    if not m:
        return {}
    v = getattr(m, "VOICES", {})
    return v() if callable(v) else v


# Compat com quem importa VOICES direto (rótulos são iguais entre engines).
VOICES = tts_edge.VOICES


def engine_info() -> dict:
    """Metadados para o /api/health — QUAL engine e se é soberano (local)."""
    e = active_engine()
    return {
        "engine": e,
        "local": e == "piper",
        "available": e != "browser",
        "voices": list(voices().keys()),
    }


async def synthesize(text: str, voice: str | None = None):
    """Sintetiza `text` pelo engine ativo, entregando bytes de áudio (async gen).
    O tipo de mídia varia por engine — use `media_type()` no StreamingResponse."""
    m = _module(active_engine())
    if not m:
        return
    async for chunk in m.synthesize(text, voice):
        yield chunk
