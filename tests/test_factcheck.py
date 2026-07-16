"""Verificação de fatos (M8, Épico 8.2). Corroboração + deriva numérica,
determinísticas. Hook do learner avisa contradição ao re-estudar.
"""

import asyncio

from fastapi.testclient import TestClient

from app import app
from src import factcheck as F
from src import runtime as rt
from src.learner import LearningEngine

client = TestClient(app)


# ── Extração de fatos ─────────────────────────────────────────
def test_extract_anos_e_quantidades():
    f = F.extract_facts("Fundado em 1969, cresceu 27% e atingiu 3 milhões de usuários.")
    assert "ano:1969" in f
    assert any(x.startswith("qty:27") for x in f)
    assert any("milho" in x for x in f)


def test_ignora_numeros_sem_unidade():
    # números soltos (sem unidade nem cara de ano) não viram fato
    assert F.extract_facts("comprei 3 itens e 5 coisas") == set()


# ── Corroboração ──────────────────────────────────────────────
def test_corroboracao_alta_quando_fatos_batem():
    known = ["A missão Apollo 11 pousou na Lua em 1969."]
    r = F.corroboration("Em 1969 o homem pisou na Lua.", known)
    assert r["score"] == 1.0 and r["note"] is None


def test_corroboracao_baixa_sinaliza_fato_sem_apoio():
    known = ["O evento ocorreu em 1969."]
    r = F.corroboration("Na verdade foi em 1971 e custou 5 bilhões.", known)
    assert r["score"] < 0.5 and r["note"] and "1971" in " ".join(r["unsupported"] and
                                                                 [str(u) for u in r["unsupported"]])


def test_corroboracao_sem_fatos_nao_sinaliza():
    r = F.corroboration("Um texto reflexivo sem números nem datas.", ["qualquer base"])
    assert r["score"] == 1.0 and r["note"] is None


# ── Deriva numérica ───────────────────────────────────────────
def test_deriva_detecta_data_trocada():
    d = F.numeric_drift("Criado em 1985 por engenheiros.",
                        "Criado em 1991, segundo novas fontes.")
    assert d["drift"] is True and "1985" in d["note"] and "1991" in d["note"]


def test_sem_deriva_quando_datas_batem():
    d = F.numeric_drift("Foi em 1985.", "Confirmado: 1985 mesmo.")
    assert d["drift"] is False and d["note"] is None


# ── Endpoint ──────────────────────────────────────────────────
def test_endpoint_factcheck(monkeypatch):
    class _RAG:
        def recall(self, q, n): return [{"content": "Ocorreu em 1969 na Lua."}]
    monkeypatch.setattr(rt, "memory", None, raising=False)
    monkeypatch.setattr(rt, "rag", _RAG(), raising=False)
    d = client.post("/api/factcheck",
                    json={"topic": "Apollo 11", "text": "Foi em 1971."}).json()
    assert d["ok"] is True and d["score"] < 0.5 and d["note"]


# ── Hook do learner ───────────────────────────────────────────
def test_learner_check_fact_drift_notifica():
    notes = []

    class _DB:
        def add_notification(self, msg, kind="info"): notes.append(msg)

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng._check_fact_drift("Empresa X", "Fundada em 1998.", "Fundada em 2001.")
    assert notes and "Fato mudou" in notes[0]


def test_learner_sem_drift_nao_notifica():
    notes = []

    class _DB:
        def add_notification(self, msg, kind="info"): notes.append(msg)

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng._check_fact_drift("Empresa X", "Fundada em 1998.", "Fundada em 1998, cresceu.")
    assert notes == []


# ── Fidelidade à fonte via juiz LLM (P2.1) ─────────────────────
def test_parse_groundedness_sim_e_nao():
    assert F.parse_groundedness("sim") == "verified"
    assert F.parse_groundedness("Sim, é fiel.") == "verified"
    assert F.parse_groundedness("não") == "failed"
    assert F.parse_groundedness("nao, inventou dados") == "failed"


def test_parse_groundedness_inconclusivo_vira_none():
    assert F.parse_groundedness("talvez") is None
    assert F.parse_groundedness("") is None
    assert F.parse_groundedness(None) is None


def test_groundedness_prompt_inclui_fonte_e_resumo():
    p = F.GROUNDEDNESS_PROMPT.format(source="A fonte diz X.", summary="O resumo diz Y.")
    assert "A fonte diz X." in p and "O resumo diz Y." in p


# ── _verify_summary (learner.py) — amostra 1/N, nunca derruba o pipeline ──
def test_verify_summary_marca_verified(monkeypatch):
    eng = LearningEngine.__new__(LearningEngine)
    eng.gpu_gate = None
    eng.summarize_model = "modelo"
    eng._llm_lock = asyncio.Lock()
    monkeypatch.setattr("src.learner.chat_resilient", lambda *a, **k: "sim")
    result = asyncio.run(eng._verify_summary("resumo qualquer", "fonte qualquer"))
    assert result == "verified"


def test_verify_summary_marca_failed(monkeypatch):
    eng = LearningEngine.__new__(LearningEngine)
    eng.gpu_gate = None
    eng.summarize_model = "modelo"
    eng._llm_lock = asyncio.Lock()
    monkeypatch.setattr("src.learner.chat_resilient", lambda *a, **k: "não")
    result = asyncio.run(eng._verify_summary("resumo qualquer", "fonte qualquer"))
    assert result == "failed"


def test_verify_summary_erro_nunca_derruba_pipeline(monkeypatch):
    eng = LearningEngine.__new__(LearningEngine)
    eng.gpu_gate = None
    eng.summarize_model = "modelo"
    eng._llm_lock = asyncio.Lock()

    def _raise(*a, **k):
        raise RuntimeError("motor fora do ar")
    monkeypatch.setattr("src.learner.chat_resilient", _raise)
    result = asyncio.run(eng._verify_summary("resumo", "fonte"))
    assert result is None  # NUNCA propaga a exceção


# ── Qualidade real via juiz LLM (P2.5) ──────────────────────────
def test_parse_quality_verdict_sim_e_nao():
    assert F.parse_quality_verdict("sim") is True
    assert F.parse_quality_verdict("Sim, passa nos 3.") is True
    assert F.parse_quality_verdict("não") is False
    assert F.parse_quality_verdict("nao, é genérico demais") is False


def test_parse_quality_verdict_inconclusivo_vira_none():
    assert F.parse_quality_verdict("talvez") is None
    assert F.parse_quality_verdict("") is None
    assert F.parse_quality_verdict(None) is None


def test_quality_prompt_inclui_topico_e_resumo():
    p = F.QUALITY_PROMPT.format(topic="Kafka", summary="Resumo sobre partições.")
    assert "Kafka" in p and "Resumo sobre partições." in p
