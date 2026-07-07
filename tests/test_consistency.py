"""Self-consistency barata (M7, Épico 7.3). Reconciliação determinística de 2–3
amostras; amostragem com sampler injetável (sem LLM real nos testes).
"""
from fastapi.testclient import TestClient

from app import app
from src import consistency as C

client = TestClient(app)


def test_agreement_alto_para_respostas_parecidas():
    a = ["A fotossíntese converte luz em glicose e oxigênio",
         "Fotossíntese converte luz solar em glicose e oxigênio nas plantas"]
    assert C.pairwise_agreement(a) >= 0.35


def test_agreement_baixo_para_respostas_divergentes():
    a = ["Ada Lovelace foi matemática britânica pioneira da computação",
         "Ada Lovelace descobriu a penicilina no século vinte"]
    assert C.pairwise_agreement(a) < 0.35


def test_reconcile_concorda():
    r = C.reconcile(["python é linguagem interpretada de alto nível",
                     "python é uma linguagem interpretada de alto nível popular"])
    assert r["agreed"] is True and r["note"] is None and r["consensus"]


def test_reconcile_diverge_sinaliza():
    r = C.reconcile(["a capital é Paris na França europeia",
                     "o resultado é quarenta e dois graus celsius agora"])
    assert r["agreed"] is False and r["note"]


def test_reconcile_uma_amostra_nao_verifica():
    r = C.reconcile(["resposta única"])
    assert r["agreed"] is True and r["n"] == 1


def test_self_consistent_com_sampler_fake():
    # sampler que sempre concorda → alta consistência
    r = C.self_consistent_answer("o que é X?",
                                 lambda q: "X é um conceito de teste bem definido", n=3)
    assert r["agreed"] is True and len(r["samples"]) == 3
    # sampler que varia muito → diverge
    respostas = iter(["gato preto subiu telhado alto",
                      "avião azul voou céu distante",
                      "montanha verde cresceu vale fundo"])
    r2 = C.self_consistent_answer("pergunta ambígua", lambda q: next(respostas), n=3)
    assert r2["agreed"] is False and r2["note"]


def test_self_consistent_ignora_amostra_vazia():
    respostas = iter(["resposta boa e completa aqui", "", "  "])
    r = C.self_consistent_answer("q", lambda q: next(respostas), n=3)
    assert len(r["samples"]) == 1


def test_endpoint_pergunta_vazia():
    assert client.post("/api/consistency", json={"question": ""}).json()["ok"] is False
