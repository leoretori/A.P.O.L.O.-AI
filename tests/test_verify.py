"""Cadeia de verificação anti-alucinação (M7, Épico 7.2).

Determinística: mede se uma resposta factual está ancorada nas fontes da base e
sinaliza incerteza quando não está. Sem LLM.
"""
from fastapi.testclient import TestClient

from app import app
from src import verify as V
from src import runtime as rt

client = TestClient(app)


# ── Classificação factual vs não-factual ──────────────────────
def test_perguntas_factuais():
    assert V.is_factual_question("O que é fotossíntese?")
    assert V.is_factual_question("Quem inventou o telefone?")
    assert V.is_factual_question("como funciona o TCP?")
    assert V.is_factual_question("quantos planetas tem o sistema solar")


def test_nao_factuais_nao_verificam():
    assert not V.is_factual_question("escreva um poema sobre o mar")
    assert not V.is_factual_question("implemente um quicksort em python")
    assert not V.is_factual_question("o que você acha do meu código?")
    assert not V.is_factual_question("oi, tudo bem?")


# ── Score de ancoragem ────────────────────────────────────────
def test_grounding_alto_quando_resposta_vem_das_fontes():
    fontes = [{"content": "A fotossíntese converte luz solar, água e gás carbônico "
                          "em glicose e oxigênio nos cloroplastos das plantas."}]
    resp = "A fotossíntese converte luz solar e gás carbônico em glicose e oxigênio."
    assert V.grounding_score(resp, fontes) >= 0.5


def test_grounding_baixo_quando_resposta_diverge():
    fontes = [{"content": "A fotossíntese ocorre nos cloroplastos das plantas."}]
    resp = "O imposto de renda tem alíquota progressiva até 27 por cento no Brasil."
    assert V.grounding_score(resp, fontes) < 0.25


def test_grounding_aceita_strings_e_snippet():
    assert V.grounding_score("kubernetes orquestra containers",
                             ["kubernetes orquestra containers em cluster"]) >= 0.5
    assert V.grounding_score("kubernetes orquestra containers",
                             [{"snippet": "kubernetes orquestra containers"}]) >= 0.5


# ── Veredito ──────────────────────────────────────────────────
def test_verdict_nao_factual_nao_sinaliza():
    v = V.verdict("escreva um haiku", "qualquer coisa", [])
    assert v["checked"] is False and v["grounded"] is True and v["note"] is None


def test_verdict_factual_sem_fonte_avisa():
    v = V.verdict("quem foi Ada Lovelace?", "Foi uma matemática britânica.", [])
    assert v["checked"] and v["grounded"] is False and v["label"] == "sem_fonte"
    assert "base" in v["note"]


def test_verdict_factual_ancorado_ok():
    fontes = [{"content": "Ada Lovelace foi matemática britânica, pioneira da "
                          "computação, escreveu o primeiro algoritmo."}]
    v = V.verdict("quem foi Ada Lovelace?",
                  "Ada Lovelace foi uma matemática britânica pioneira da computação.",
                  fontes)
    assert v["checked"] and v["grounded"] is True and v["label"] in ("alta", "media")
    assert v["note"] is None


def test_verdict_factual_desancorado_sinaliza():
    fontes = [{"content": "Python é uma linguagem de programação interpretada."}]
    v = V.verdict("quem foi Ada Lovelace?",
                  "Ada Lovelace descobriu a penicilina em mil novecentos e vinte oito.",
                  fontes)
    assert v["grounded"] is False and v["label"] == "baixa" and v["note"]


# ── Endpoint ──────────────────────────────────────────────────
def test_endpoint_nao_factual(monkeypatch):
    r = client.post("/api/verify", json={"question": "escreva um conto",
                                         "answer": "Era uma vez..."}).json()
    assert r["checked"] is False and r["sources_count"] == 0


def test_endpoint_factual_usa_recall(monkeypatch):
    # injeta um RAG fake com fonte relevante
    class _RAG:
        def recall(self, q, n): return [{"snippet": "Ada Lovelace foi matemática "
                                          "britânica pioneira da computação"}]
    monkeypatch.setattr(rt, "memory", None, raising=False)
    monkeypatch.setattr(rt, "rag", _RAG(), raising=False)
    r = client.post("/api/verify", json={
        "question": "quem foi Ada Lovelace?",
        "answer": "Ada Lovelace foi uma matemática britânica pioneira da computação."}).json()
    assert r["checked"] is True and r["grounded"] is True and r["sources_count"] == 1
