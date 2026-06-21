"""TTS local via edge-tts (opcional).

Vozes neurais de alta qualidade (mesmo nível do Azure TTS) sem custo e
sem GPU — edge-tts usa a infraestrutura do Microsoft Edge offline.

Instalar: pip install edge-tts
Vozes PT-BR disponíveis:
  pt-BR-FranciscaNeural  (feminino, padrão)
  pt-BR-AntonioNeural    (masculino)

Se não instalado, o frontend usa speechSynthesis do navegador como fallback.
"""

import logging

logger = logging.getLogger(__name__)

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


async def synthesize(text: str, voice: str = DEFAULT_VOICE):
    """Gerador assíncrono de chunks de áudio MP3 via edge-tts.

    Yields bytes diretamente — para ser usado em StreamingResponse.
    Limita a 3000 chars para não travar o pipeline de voz.
    """
    import edge_tts
    text = (text or "").strip()[:3000]
    if not text:
        return
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]
