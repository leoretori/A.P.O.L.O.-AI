"""Voz — transcrição (STT) e síntese de fala (TTS).

Rotas: /api/stt (faster-whisper local), /api/tts (edge-tts).
Extraído de app.py na M1 do JARVIS_ROADMAP. Sem estado global — os módulos de
voz são opcionais e checados em runtime (fallback do navegador quando ausentes).

NOTA (JARVIS_ROADMAP L1): o TTS via edge-tts usa a NUVEM da Microsoft — a M3
troca por um TTS 100% local (Piper) para fechar a soberania.
"""
import asyncio
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()


@router.post("/api/stt")
async def stt_transcribe(request: Request):
    """Transcrição de voz local via faster-whisper.
    Recebe o áudio bruto (WebM/WAV) como body da requisição.
    Se faster-whisper não estiver instalado, retorna {ok:false} e o frontend
    usa o fallback Web Speech API do navegador."""
    from src.whisper_stt import transcribe, is_available
    if not is_available():
        return {"ok": False, "error": "faster-whisper não instalado",
                "hint": "pip install faster-whisper"}
    audio = await request.body()
    if len(audio) < 100:
        return {"ok": False, "error": "Áudio muito curto ou vazio"}
    size = os.getenv("WHISPER_MODEL", "base")
    text = await asyncio.to_thread(transcribe, audio, size)
    if text:
        return {"ok": True, "text": text}
    return {"ok": False, "error": "Não foi possível transcrever o áudio"}


@router.get("/api/tts")
async def tts_endpoint(text: str = "", voice: str = "pt-BR-FranciscaNeural"):
    """TTS de alta qualidade via edge-tts (vozes neurais PT-BR).
    Retorna áudio MP3 em streaming — o frontend toca via Audio API.
    Fallback: speechSynthesis do navegador (browser) quando não instalado."""
    from src.tts import is_available, synthesize
    if not is_available():
        return JSONResponse({"error": "edge-tts não instalado", "hint": "pip install edge-tts"},
                            status_code=503)
    clean = (text or "").strip()
    if not clean:
        return JSONResponse({"error": "texto vazio"}, status_code=400)
    return StreamingResponse(
        synthesize(clean, voice),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
