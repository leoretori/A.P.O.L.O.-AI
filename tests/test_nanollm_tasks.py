"""Tarefas do Nano no produto (Épico 3.3): título com portão de qualidade."""

import asyncio

import pytest

import src.chat_common as cc
from src import runtime as rt
from src.nanollm.tasks import (
    binary_prompt,
    extract_title,
    nano_binary_classify,
    nano_session_title,
    title_ok,
    title_prompt,
)


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


# --------------------------------------------------------- classificação setor
def test_nano_classify_sector_casa_rotulo():
    from src.nanollm.tasks import nano_classify_sector

    labels = ["backend_apis", "frontend_web", "data_ml"]
    assert nano_classify_sector(FakeEngine("backend_apis"), "FastAPI", labels) == "backend_apis"
    # tokens extras depois do slug ainda casam (prefixo)
    assert nano_classify_sector(FakeEngine("frontend_web e mais"), "React", labels) == "frontend_web"


def test_nano_classify_sector_sem_casar_vira_none():
    from src.nanollm.tasks import nano_classify_sector

    labels = ["backend_apis", "frontend_web"]
    assert nano_classify_sector(FakeEngine("xyz nada"), "?", labels) is None
    assert nano_classify_sector(FakeEngine("backend_apis"), "?", []) is None
    assert nano_classify_sector(None, "?", labels) is None
    assert nano_classify_sector(FakeEngine(raises=True), "?", labels) is None


# ------------------------------------------------ gate binário (M27+)
def test_binary_prompt_usa_a_pergunta_como_continuacao():
    p = binary_prompt("FastAPI com pydantic", "É Backend & APIs?")
    assert p.endswith("É Backend & APIs? ")
    assert "FastAPI" in p


def test_nano_binary_classify_sim_e_nao():
    assert nano_binary_classify(FakeEngine("sim"), "texto", "É X?") is True
    assert nano_binary_classify(FakeEngine("não"), "texto", "É X?") is False
    assert nano_binary_classify(FakeEngine("nao"), "texto", "É X?") is False  # sem acento
    assert nano_binary_classify(FakeEngine("s"), "texto", "É X?") is True


def test_nano_binary_classify_tokens_extras_ainda_casam():
    assert nano_binary_classify(FakeEngine("sim, com certeza"), "texto", "É X?") is True
    assert nano_binary_classify(FakeEngine("não é sobre isso"), "texto", "É X?") is False


def test_nano_binary_classify_sem_casar_vira_none():
    assert nano_binary_classify(FakeEngine("talvez"), "texto", "É X?") is None
    assert nano_binary_classify(FakeEngine(""), "texto", "É X?") is None


def test_nano_binary_classify_indisponivel_ou_erro_vira_none():
    assert nano_binary_classify(None, "texto", "É X?") is None
    assert nano_binary_classify(FakeEngine(avail=False), "texto", "É X?") is None
    assert nano_binary_classify(FakeEngine(raises=True), "texto", "É X?") is None


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


def test_fallback_do_titulo_cede_gpu_ao_usuario(monkeypatch):
    """O título roda em background (create_task, não awaited pelo stream) — se o
    usuário mandar a 2ª mensagem rápido, essa geração não pode disputar o lock do
    motor sem ceder (mesma classe de bug do flywheel/blind_eval/consolidação)."""
    db = FakeDB()
    monkeypatch.setattr(rt, "db", db)
    monkeypatch.setattr(rt, "nano", None)          # força o caminho de fallback
    monkeypatch.setattr(cc, "chat_resilient", lambda *a, **k: "Título")
    calls = {"n": 0}

    class _FakeGate:
        def wait_for_idle_sync(self, *a, **k):
            calls["n"] += 1

    monkeypatch.setattr(rt, "gpu_gate", _FakeGate())
    asyncio.run(cc.generate_session_title("s4", "pergunta"))
    assert calls["n"] == 1
    assert db.saved["s4"] == "Título"
