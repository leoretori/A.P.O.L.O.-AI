"""Palavra de ativação (M5, Épico 5.1). Detecção determinística e local:
normaliza, tolera preâmbulo e erro de transcrição (edit-distance ≤1), e devolve
o comando após a wake word. Endpoints config/detect.
"""
from fastapi.testclient import TestClient

from app import app
from src import wake

client = TestClient(app)


# ── Detecção pura ─────────────────────────────────────────────
def test_detecta_apolo_e_extrai_comando():
    d = wake.detect("Apolo, que horas são?")
    assert d["woke"] is True and d["phrase"] == "apolo"
    assert d["command"] == "que horas sao"


def test_tolera_preambulo_e_acentos():
    assert wake.detect("Ei Ápolo!")["woke"] is True
    assert wake.detect("ok jarvis toca musica")["woke"] is True
    assert wake.detect("ok jarvis toca musica")["command"] == "toca musica"


def test_tolera_erro_de_transcricao_edit_distance_1():
    # Whisper às vezes ouve "apollo" ou "ápolho".
    assert wake.detect("apollo que dia é hoje")["woke"] is True
    assert wake.detect("apolho me ajuda")["woke"] is True


def test_nao_dispara_sem_wake_word():
    assert wake.detect("que horas são?")["woke"] is False
    assert wake.detect("")["woke"] is False
    # palavra parecida mas longe demais não dispara (evita falso positivo)
    assert wake.detect("apolinario chegou")["woke"] is False


def test_wake_word_no_meio_nao_dispara():
    # 'apolo' no meio da frase não é ativação (reduz falso positivo).
    assert wake.detect("eu falei com o apolo ontem")["woke"] is False


def test_wake_words_configuravel(monkeypatch):
    monkeypatch.setenv("WAKE_WORDS", "sexta, computador")
    assert set(wake.wake_words()) == {"sexta", "computador"}
    assert wake.detect("computador, ligue a luz")["woke"] is True


def test_edit_distance_le1_unit():
    assert wake._edit_distance_le1("apolo", "apolo")
    assert wake._edit_distance_le1("apolo", "apollo")   # inserção
    assert wake._edit_distance_le1("apolo", "apola")    # substituição
    assert wake._edit_distance_le1("apolo", "apol")     # deleção
    assert not wake._edit_distance_le1("apolo", "apoxx")
    assert not wake._edit_distance_le1("apolo", "jarvis")


# ── Endpoints ─────────────────────────────────────────────────
def test_endpoint_config():
    d = client.get("/api/wake/config").json()
    assert "enabled" in d and "apolo" in d["phrases"]


def test_endpoint_detect():
    d = client.post("/api/wake/detect", json={"text": "apolo que horas são"}).json()
    assert d["woke"] is True and d["command"] == "que horas sao"
    d2 = client.post("/api/wake/detect", json={"text": "nada aqui"}).json()
    assert d2["woke"] is False
