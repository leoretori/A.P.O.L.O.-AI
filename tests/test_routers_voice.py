"""Router de voz (routers/voice.py) — TTS com engine soberano (Piper local) e
fallback (edge nuvem / browser). Testa a resolução de engine + cabeçalhos que
reportam qual engine respondeu, sem exigir piper/edge instalados."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import tts, tts_edge, tts_piper
from routers.voice import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _set(monkeypatch, *, piper, edge):
    monkeypatch.delenv("TTS_ENGINE", raising=False)
    monkeypatch.setattr(tts_piper, "is_available", lambda: piper)
    monkeypatch.setattr(tts_edge, "is_available", lambda: edge)


def test_tts_503_quando_so_ha_browser(monkeypatch):
    _set(monkeypatch, piper=False, edge=False)
    r = _client().get("/api/tts?text=olá")
    assert r.status_code == 503
    assert r.json()["engine"] == "browser"


def test_tts_texto_vazio_400(monkeypatch):
    _set(monkeypatch, piper=False, edge=True)
    assert _client().get("/api/tts?text=").status_code == 400


def test_tts_usa_piper_e_reporta_local(monkeypatch):
    _set(monkeypatch, piper=True, edge=True)

    async def fake_synth(text, voice=None):
        yield b"WAVDATA"
    monkeypatch.setattr(tts_piper, "synthesize", fake_synth)

    r = _client().get("/api/tts?text=olá")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.headers["x-tts-engine"] == "piper"
    assert r.headers["x-tts-local"] == "true"
    assert r.content == b"WAVDATA"


def test_tts_fallback_edge_reporta_nuvem(monkeypatch):
    _set(monkeypatch, piper=False, edge=True)

    async def fake_synth(text, voice=None):
        yield b"ID3MP3"
    monkeypatch.setattr(tts_edge, "synthesize", fake_synth)

    r = _client().get("/api/tts?text=olá")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/mpeg")
    assert r.headers["x-tts-engine"] == "edge-tts"
    assert r.headers["x-tts-local"] == "false"
