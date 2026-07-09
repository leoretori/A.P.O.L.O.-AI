"""Tarefas do Nano no produto (Épico 3.3): título com portão de qualidade."""

import asyncio

import pytest

import src.chat_common as cc
from src import runtime as rt
from src.nanollm.tasks import extract_title, nano_session_title, title_ok, title_prompt


# ------------------------------------------------------------ portão/extração
def test_title_prompt_usa_padrao_do_corpus():
    p = title_prompt("Como faço um loop em Python?  ")
    assert p.endswith("Tópico: ")
    assert "Como faço um loop" in p


@pytest.mark.parametrize("bruto,esperado", [
    ("Loops em Python\nCategoria: backend", "Loops em Python"),
    ("  **Async no FastAPI**. E mais coisa", "Async no FastAPI"),
    ("'Memória do Apolo': detalhes extras aqui", "Memória do Apolo"),
])
def test_extract_title(bruto, esperado):
    assert extract_title(bruto) == esperado


def test_extract_title_corta_em_60_chars_na_palavra():
    longo = "palavra " * 20
    t = extract_title(longo)
    assert len(t) <= 60 and not t.endswith(" ")


@pytest.mark.parametrize("bom", [
    "Loops em Python", "Async no FastAPI", "Memória episódica do Apolo",
])
def test_title_ok_aceita(bom):
    assert title_ok(bom)


@pytest.mark.parametrize("ruim", [
    "", "ab", "x" * 61,                                  # tamanho
    "o que é o que é o que é",                            # loop degenerativo
    "## Conceitos-chave",                                 # markdown
    "veja https://x.com",                                 # url
    "1234 5678 !!!",                                      # pouca letra
    "um dois três quatro cinco seis sete oito nove",      # palavras demais
])
def test_title_ok_recusa(ruim):
    assert not title_ok(ruim)


def test_title_relevant():
    from src.nanollm.tasks import title_relevant

    assert title_relevant("Loops em Python", "Como faço um loop em Python?")
    assert title_relevant("Memória episódica", "como funciona a memoria do Apolo?")  # sem acento
    assert not title_relevant("AWS S3", "Como faço um loop assíncrono em Python?")  # caso real do v1
    assert not title_relevant("", "mensagem qualquer")


# ------------------------------------------------------- nano_session_title
class FakeEngine:
    def __init__(self, text="Loops em Python", raises=False, avail=True):
        self._text, self._raises, self._avail = text, raises, avail

    def available(self):
        return self._avail

    def complete(self, prompt, max_tokens=60, temperature=0.8, top_k=40, seed=None):
        if self._raises:
            raise RuntimeError("boom")
        return {"text": self._text, "tokens": 3, "ms": 40}


def test_nano_title_bom():
    t = nano_session_title(FakeEngine("Loops em Python\nlixo"), "como faço um loop?")
    assert t == "Loops em Python"


def test_nano_title_reprovado_vira_none():
    assert nano_session_title(FakeEngine("o que é o que é o que é"), "msg") is None


def test_nano_title_irrelevante_vira_none():
    # bem-formado mas sem relação com a mensagem → portão de relevância barra
    assert nano_session_title(FakeEngine("AWS S3"), "como faço um loop em python?") is None


def test_nano_title_indisponivel_ou_erro_vira_none():
    assert nano_session_title(None, "msg") is None
    assert nano_session_title(FakeEngine(avail=False), "msg") is None
    assert nano_session_title(FakeEngine(raises=True), "msg") is None


# ----------------------------------------- integração generate_session_title
class FakeDB:
    def __init__(self):
        self.saved = {}

    def save_session_title(self, sid, title):
        self.saved[sid] = title


def test_chat_usa_nano_quando_bom(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(rt, "db", db)
    monkeypatch.setattr(rt, "nano", FakeEngine("Async no FastAPI"))
    chamou_llm = []
    monkeypatch.setattr(cc, "chat_resilient",
                        lambda *a, **k: chamou_llm.append(1) or "Fallback")
    asyncio.run(cc.generate_session_title("s1", "como usar async?"))
    assert db.saved["s1"] == "Async no FastAPI"
    assert not chamou_llm  # LLM grande nem foi acordado


def test_chat_cai_no_fallback_quando_nano_fraco(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(rt, "db", db)
    monkeypatch.setattr(rt, "nano", FakeEngine("o que é o que é o que é"))
    monkeypatch.setattr(cc, "chat_resilient", lambda *a, **k: "Título do LLM grande")
    asyncio.run(cc.generate_session_title("s2", "pergunta"))
    assert db.saved["s2"] == "Título do LLM grande"


def test_chat_sem_nano_segue_como_antes(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(rt, "db", db)
    monkeypatch.setattr(rt, "nano", None)
    monkeypatch.setattr(cc, "chat_resilient", lambda *a, **k: "Clássico")
    asyncio.run(cc.generate_session_title("s3", "oi"))
    assert db.saved["s3"] == "Clássico"
