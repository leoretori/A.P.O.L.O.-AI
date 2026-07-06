"""TTS soberano (M3, Épico 3.1): fachada que prefere o Piper LOCAL sobre o
edge-tts (nuvem) e reporta honestamente se a voz é local. Os testes usam
monkeypatch nos engines — não exigem piper/edge instalados de verdade."""
import asyncio

import pytest

from src import tts, tts_edge, tts_piper


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TTS_ENGINE", raising=False)


def _set(monkeypatch, *, piper: bool, edge: bool):
    monkeypatch.setattr(tts_piper, "is_available", lambda: piper)
    monkeypatch.setattr(tts_edge, "is_available", lambda: edge)


# ── Resolução do engine ativo ─────────────────────────────────
def test_prefere_piper_quando_disponivel(monkeypatch):
    _set(monkeypatch, piper=True, edge=True)
    assert tts.active_engine() == "piper"       # soberania primeiro
    assert tts.is_local() is True
    assert tts.media_type() == "audio/wav"


def test_cai_para_edge_sem_piper(monkeypatch):
    _set(monkeypatch, piper=False, edge=True)
    assert tts.active_engine() == "edge-tts"
    assert tts.is_local() is False              # nuvem, honesto
    assert tts.media_type() == "audio/mpeg"


def test_browser_quando_nenhum_engine(monkeypatch):
    _set(monkeypatch, piper=False, edge=False)
    assert tts.active_engine() == "browser"
    assert tts.is_available() is False
    assert tts.is_local() is False


def test_tts_engine_forcado_por_env(monkeypatch):
    _set(monkeypatch, piper=True, edge=True)
    monkeypatch.setenv("TTS_ENGINE", "edge")
    assert tts.active_engine() == "edge-tts"     # força nuvem mesmo com piper


def test_engine_forcado_indisponivel_cai_para_auto(monkeypatch):
    _set(monkeypatch, piper=False, edge=True)
    monkeypatch.setenv("TTS_ENGINE", "piper")    # forçado mas indisponível
    assert tts.active_engine() == "edge-tts"     # auto → edge


def test_engine_info_reporta_honestamente(monkeypatch):
    _set(monkeypatch, piper=True, edge=True)
    info = tts.engine_info()
    assert info == {"engine": "piper", "local": True, "available": True,
                    "voices": info["voices"]}


# ── Dispatch da síntese ───────────────────────────────────────
def test_synthesize_despacha_para_o_engine_ativo(monkeypatch):
    _set(monkeypatch, piper=True, edge=True)

    async def fake_piper_synth(text, voice=None):
        yield b"WAVDATA"
    monkeypatch.setattr(tts_piper, "synthesize", fake_piper_synth)

    async def _collect():
        return b"".join([c async for c in tts.synthesize("olá", None)])
    assert asyncio.run(_collect()) == b"WAVDATA"


def test_synthesize_browser_nao_produz_audio(monkeypatch):
    _set(monkeypatch, piper=False, edge=False)

    async def _collect():
        return [c async for c in tts.synthesize("olá")]
    assert asyncio.run(_collect()) == []


# ── Engine Piper: disponibilidade depende de pacote E modelo ──
def test_piper_indisponivel_sem_modelo(monkeypatch):
    monkeypatch.setattr(tts_piper, "_model_path", lambda voice=None: None)
    assert tts_piper.is_available() is False     # sem modelo → indisponível


def test_piper_voices_vazio_sem_modelo(monkeypatch):
    monkeypatch.setattr(tts_piper, "_model_path", lambda voice=None: None)
    assert tts_piper.VOICES() == {}


def test_piper_media_type_e_local():
    assert tts_piper.MEDIA_TYPE == "audio/wav"
    assert tts_piper.LOCAL is True
    assert tts_edge.LOCAL is False               # edge é nuvem
