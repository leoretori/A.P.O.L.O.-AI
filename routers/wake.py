"""Palavra de ativação (M5, Épico 5.1) — "Apolo"/"Jarvis".

A escuta contínua do frontend transcreve trechos curtos (Whisper local) e pergunta
ao servidor se a wake word apareceu. Detecção 100% local e determinística (src/wake.py).

Rotas:
  GET  /api/wake/config   — se está ligada + as wake words configuradas
  POST /api/wake/detect   — {text} → {woke, phrase, command}
"""
from fastapi import APIRouter

from src import wake

router = APIRouter()


@router.get("/api/wake/config")
async def wake_config():
    return {"enabled": wake.is_enabled(), "phrases": wake.wake_words()}


@router.post("/api/wake/detect")
async def wake_detect(payload: dict):
    text = (payload or {}).get("text", "")
    return wake.detect(text)
