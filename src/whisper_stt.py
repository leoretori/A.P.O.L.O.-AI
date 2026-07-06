"""STT local via faster-whisper (opcional).

Se faster-whisper não estiver instalado, is_available() retorna False e o
frontend usa o fallback Web Speech API do navegador. Para instalar:
    pip install faster-whisper

Modelos suportados (CPU): tiny (75MB, rápido) | base (145MB, bom) | small (461MB, melhor)
Configurar via env WHISPER_MODEL=base (padrão).
"""

import io
import logging

logger = logging.getLogger(__name__)

_model = None
_model_size: str | None = None


def is_available() -> bool:
    """Verifica se faster-whisper está instalado (o motor de STT existe)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def is_ready() -> bool:
    """True se o modelo já está CARREGADO na memória — a 1ª transcrição sai sem
    cold-start (STT 'sempre pronto', M3 Épico 3.2)."""
    return _model is not None


def warmup(size: str = "base") -> bool:
    """Pré-carrega o modelo Whisper no boot, para a primeira ditada não pagar o
    custo de carregar o modelo (segundos no CPU). Retorna True se ficou pronto."""
    if not is_available():
        return False
    try:
        _load(size)
        return True
    except Exception as e:
        logger.warning(f"[stt] warmup falhou: {e}")
        return False


def _load(size: str = "base"):
    global _model, _model_size
    if _model is not None and _model_size == size:
        return _model
    from faster_whisper import WhisperModel
    logger.info(f"[stt] carregando Whisper '{size}' (CPU, int8)...")
    _model = WhisperModel(size, device="cpu", compute_type="int8")
    _model_size = size
    logger.info(f"[stt] Whisper '{size}' pronto")
    return _model


def transcribe(audio_bytes: bytes, size: str = "base", language: str = "pt") -> str | None:
    """Transcreve bytes de áudio (WebM/WAV/MP4) para texto.

    Retorna None se faster-whisper não estiver instalado ou se a transcrição
    falhar — o chamador decide o fallback (Web Speech API, erro, etc.).
    """
    if not audio_bytes or len(audio_bytes) < 100:
        return None
    try:
        model = _load(size)
    except ImportError:
        return None
    except Exception as e:
        logger.warning(f"[stt] erro ao carregar modelo: {e}")
        return None
    try:
        segments, _info = model.transcribe(
            io.BytesIO(audio_bytes),
            language=language,
            beam_size=5,
            vad_filter=True,       # remove silêncio automaticamente
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return text or None
    except Exception as e:
        logger.warning(f"[stt] transcrição falhou: {e}")
        return None
