"""Engine TTS Piper — voz neural 100% LOCAL, roda no CPU (M3, Épico 3.1).

Piper (https://github.com/rhasspy/piper) é um TTS neural leve que roda offline no
CPU — sem nuvem, sem GPU. É o caminho SOBERANO de voz do A.P.O.L.O., preferido
sobre o edge-tts (que é nuvem).

Para ativar, o usuário instala o pacote e baixa um modelo de voz PT-BR:
    pip install piper-tts
    # baixe um modelo .onnx + .onnx.json (ex.: pt_BR-faber-medium) e aponte:
    export PIPER_MODEL=/caminho/pt_BR-faber-medium.onnx
    # ou coloque em ./models/piper/  (busca automática)

Enquanto não houver pacote + modelo, `is_available()` é False e o TTS cai para o
edge-tts (fallback) — a soberania fica pendente de instalação, não quebrada.
"""
import glob
import io
import logging
import os
import wave

logger = logging.getLogger("apolo.tts.piper")

MEDIA_TYPE = "audio/wav"       # Piper entrega PCM → embrulhamos em WAV
LOCAL = True                   # 100% local, roda no CPU

# Rótulos amigáveis → nome/arquivo do modelo. Com um único modelo instalado,
# ambos apontam para ele; o usuário pode sobrescrever com PIPER_MODEL/_MODEL_M.
DEFAULT_VOICE = "local"


def _model_path(voice: str | None = None) -> str | None:
    """Resolve o caminho do modelo .onnx: env PIPER_MODEL (ou PIPER_MODEL_M para
    a voz masculina) → busca em models/piper e data/piper. None se não achar."""
    if voice == "masculino":
        env = os.getenv("PIPER_MODEL_M", "").strip()
        if env and os.path.exists(env):
            return env
    env = os.getenv("PIPER_MODEL", "").strip()
    if env and os.path.exists(env):
        return env
    for pat in ("models/piper/*.onnx", "data/piper/*.onnx"):
        found = sorted(glob.glob(pat))
        if found:
            return found[0]
    return None


def VOICES() -> dict:  # noqa: N802 — função (o modelo pode aparecer em runtime)
    """Vozes disponíveis (rótulo → modelo). Vazio se nenhum modelo instalado."""
    base = _model_path()
    if not base:
        return {}
    v = {"feminino": base}
    masc = _model_path("masculino")
    if masc and masc != base:
        v["masculino"] = masc
    return v


def is_available() -> bool:
    """Só está disponível se o pacote piper E um modelo de voz existirem."""
    if _model_path() is None:
        return False
    try:
        import piper  # noqa: F401
        return True
    except Exception:
        return False


def _synth_wav(text: str, model_path: str) -> bytes:
    """Sintetiza `text` num WAV completo (bytes) com o modelo Piper. Bloqueante
    (CPU) — chamar via asyncio.to_thread."""
    from piper import PiperVoice
    voice = PiperVoice.load(model_path)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        # A API do piper-tts escreve os frames WAV (configura canais/rate/width).
        voice.synthesize(text, wf)
    return buf.getvalue()


async def synthesize(text: str, voice: str | None = None):
    """Gerador assíncrono — sintetiza offline e entrega o WAV (um chunk).
    Mantém a mesma interface do engine edge (async generator de bytes)."""
    import asyncio
    text = (text or "").strip()[:3000]
    if not text:
        return
    model = _model_path(voice)
    if not model:
        logger.warning("[piper] nenhum modelo de voz encontrado")
        return
    try:
        data = await asyncio.to_thread(_synth_wav, text, model)
    except Exception as e:
        logger.warning(f"[piper] síntese falhou: {e}")
        return
    if data:
        yield data
