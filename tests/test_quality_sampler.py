"""Amostragem de qualidade real do aprendizado (P2.5) — determinística, sem LLM."""

import pytest

from src.quality_sampler import (
    append_quality_history,
    read_quality_history,
    run_quality_sample,
    run_tracked_quality_sample,
)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def sample_topics_for_quality(self, n=15):
        return self._rows[:n]


def _judge_por_palavra_chave(*, aprova="bom"):
    """Fake determinístico: aprova se a palavra-chave está no resumo."""
    def judge(topic, summary):
        return "sim" if aprova in summary.lower() else "não"
    return judge


def test_run_quality_sample_mede_pass_rate():
    db = _FakeDB([
        {"id": 1, "topic": "A", "summary": "resumo bom e específico"},
        {"id": 2, "topic": "B", "summary": "resumo genérico qualquer"},
        {"id": 3, "topic": "C", "summary": "outro resumo bom"},
    ])
    res = run_quality_sample(db, _judge_por_palavra_chave(), n=10)
    assert res["status"] == "ok"
    assert res["n"] == 3
    assert res["decided"] == 3
    assert res["passed"] == 2
    assert res["pass_rate"] == pytest.approx(66.7, abs=0.1)


def test_run_quality_sample_sem_topicos():
    res = run_quality_sample(_FakeDB([]), _judge_por_palavra_chave())
    assert res == {"status": "skipped", "reason": "sem tópicos com resumo no banco"}


def test_run_quality_sample_juiz_indeciso_nao_conta_no_pass_rate():
    db = _FakeDB([{"id": 1, "topic": "A", "summary": "x"}])

    def judge(topic, summary):
        return "talvez"
    res = run_quality_sample(db, judge)
    assert res["decided"] == 0
    assert res["pass_rate"] is None


def test_run_quality_sample_juiz_quebrado_nao_derruba():
    db = _FakeDB([{"id": 1, "topic": "A", "summary": "x"}])

    def judge(topic, summary):
        raise RuntimeError("motor fora do ar")
    res = run_quality_sample(db, judge)
    assert res["status"] == "ok"
    assert res["results"][0]["passed"] is None  # falhou "graciosamente"


# ── Placar histórico ─────────────────────────────────────────────
def test_append_e_read_quality_history_roundtrip(tmp_path):
    path = tmp_path / "hist.jsonl"
    ok = {"status": "ok", "n": 5, "decided": 5, "passed": 3, "pass_rate": 60.0}
    append_quality_history(path, ok)
    append_quality_history(path, {**ok, "passed": 4, "pass_rate": 80.0})
    hist = read_quality_history(path)
    assert len(hist) == 2
    assert hist[0]["pass_rate"] == 60.0 and hist[1]["pass_rate"] == 80.0
    assert all("timestamp" in h for h in hist)


def test_append_quality_history_ignora_status_nao_ok(tmp_path):
    path = tmp_path / "hist.jsonl"
    append_quality_history(path, {"status": "skipped", "reason": "x"})
    assert read_quality_history(path) == []


def test_read_quality_history_arquivo_inexistente(tmp_path):
    assert read_quality_history(tmp_path / "nao_existe.jsonl") == []


def test_run_tracked_quality_sample_registra_no_historico(tmp_path):
    db = _FakeDB([{"id": 1, "topic": "A", "summary": "resumo bom"}])
    path = tmp_path / "hist.jsonl"
    res = run_tracked_quality_sample(db, _judge_por_palavra_chave(),
                                     history_path=path, n=10)
    assert res["status"] == "ok"
    hist = read_quality_history(path)
    assert len(hist) == 1 and hist[0]["passed"] == 1


def test_run_tracked_quality_sample_pulado_nao_registra(tmp_path):
    path = tmp_path / "hist.jsonl"
    run_tracked_quality_sample(_FakeDB([]), _judge_por_palavra_chave(), history_path=path)
    assert read_quality_history(path) == []


# ── make_llm_quality_judge ────────────────────────────────────────
def test_make_llm_quality_judge_usa_provider(monkeypatch):
    from src.quality_sampler import make_llm_quality_judge

    class _Prov:
        def list_models(self):
            return ["apolo"]

        def complete(self, model, messages, options=None):
            return "sim"
    monkeypatch.setattr("src.providers.get_provider", lambda: _Prov())
    judge = make_llm_quality_judge(model="apolo")
    assert judge("Kafka", "resumo qualquer") == "sim"


def test_make_llm_quality_judge_cede_gpu_ao_usuario(monkeypatch):
    from src.quality_sampler import make_llm_quality_judge

    class _Prov:
        def list_models(self):
            return ["apolo"]

        def complete(self, model, messages, options=None):
            return "sim"
    monkeypatch.setattr("src.providers.get_provider", lambda: _Prov())

    calls = {"n": 0}

    class _FakeGate:
        def wait_for_idle_sync(self, *a, **k):
            calls["n"] += 1

    import src.runtime as rt
    monkeypatch.setattr(rt, "gpu_gate", _FakeGate())
    judge = make_llm_quality_judge(model="apolo")
    judge("Kafka", "resumo")
    judge("Redis", "outro resumo")
    assert calls["n"] == 2
