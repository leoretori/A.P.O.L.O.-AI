"""STT 'sempre pronto' (M3, Épico 3.2): warmup pré-carrega o Whisper para a 1ª
ditada não pagar cold-start; is_ready() reflete se o modelo está na memória.
Os testes usam um WhisperModel falso — não baixam modelo nem tocam a rede."""
import pytest

import src.whisper_stt as stt


class FakeModel:
    def __init__(self, *a, **k):
        pass
    def transcribe(self, *a, **k):
        class Seg:
            text = "olá mundo"
        return [Seg()], None


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Zera o modelo carregado entre testes e injeta o modelo falso.
    monkeypatch.setattr(stt, "_model", None, raising=False)
    monkeypatch.setattr(stt, "_model_size", None, raising=False)
    import faster_whisper
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    yield


def test_is_ready_falso_antes_do_warmup():
    assert stt.is_ready() is False


def test_warmup_carrega_o_modelo_e_fica_pronto():
    assert stt.warmup("tiny") is True
    assert stt.is_ready() is True


def test_warmup_sem_faster_whisper_retorna_false(monkeypatch):
    monkeypatch.setattr(stt, "is_available", lambda: False)
    assert stt.warmup("tiny") is False
    assert stt.is_ready() is False


def test_transcribe_apos_warmup():
    stt.warmup("tiny")
    assert stt.transcribe(b"x" * 200, "tiny") == "olá mundo"


def test_transcribe_carrega_sozinho_se_nao_aquecido():
    # Sem warmup prévio → transcribe ainda funciona (lazy load), depois fica pronto.
    assert stt.is_ready() is False
    assert stt.transcribe(b"x" * 200, "tiny") == "olá mundo"
    assert stt.is_ready() is True


def test_transcribe_audio_curto_e_none():
    assert stt.transcribe(b"", "tiny") is None
    assert stt.transcribe(b"ab", "tiny") is None
