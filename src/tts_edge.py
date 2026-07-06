"""Engine TTS edge-tts — vozes neurais PT-BR de alta qualidade.

ATENÇÃO (JARVIS_ROADMAP L1): edge-tts NÃO é local — usa a NUVEM da Microsoft
(o Edge fala com um serviço online). É ótimo em qualidade e custo zero, mas
quebra a soberania. Fica como FALLBACK quando o Piper (100% local) não está
instalado. Instalar: pip install edge-tts
"""
import logging

logger = logging.getLogger("apolo.tts.edge")

MEDIA_TYPE = "audio/mpeg"      # edge-tts entrega MP3
LOCAL = False                  # NUVEM (Microsoft)

DEFAULT_VOICE = "pt-BR-FranciscaNeural"
VOICES = {
    "feminino": "pt-BR-FranciscaNeural",
    "masculino": "pt-BR-AntonioNeural",
}


def is_available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


async def synthesize(text: str, voice: str | None = None):
    """Gerador assíncrono de chunks MP3 via edge-tts (para StreamingResponse)."""
    import edge_tts
    text = (text or "").strip()[:3000]
    if not text:
        return
    voice = voice or DEFAULT_VOICE
    # Rótulo amigável ("feminino") → nome real da voz.
    voice = VOICES.get(voice, voice)
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]
