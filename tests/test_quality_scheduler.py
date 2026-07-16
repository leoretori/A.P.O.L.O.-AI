"""Amostra de qualidade noturna (P2.5) — o ciclo agendado em app.py. Mesmo
padrão do dedup/flywheel (M25.3/P2.4)."""

import asyncio

import app as app_module


class _FakeDB:
    def __init__(self, rows=None, raise_=False):
        self._rows = rows or []
        self._raise = raise_

    def sample_topics_for_quality(self, n=15):
        if self._raise:
            raise RuntimeError("banco fora do ar")
        return self._rows[:n]


def test_run_quality_sample_cycle_sem_db_nao_levanta(monkeypatch):
    monkeypatch.setattr(app_module, "db", None)
    asyncio.run(app_module._run_quality_sample_cycle())


def test_run_quality_sample_cycle_roda_de_ponta_a_ponta(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "db", _FakeDB(
        rows=[{"id": 1, "topic": "A", "summary": "resumo bom"}]))
    monkeypatch.setattr(app_module, "QUALITY_HISTORY_PATH", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(
        "src.quality_sampler.make_llm_quality_judge",
        lambda: (lambda topic, summary: "sim"))
    asyncio.run(app_module._run_quality_sample_cycle())

    from src.quality_sampler import read_quality_history
    hist = read_quality_history(tmp_path / "hist.jsonl")
    assert len(hist) == 1 and hist[0]["passed"] == 1


def test_run_quality_sample_cycle_erro_nao_derruba_scheduler(monkeypatch):
    monkeypatch.setattr(app_module, "db", _FakeDB(raise_=True))
    monkeypatch.setattr(
        "src.quality_sampler.make_llm_quality_judge",
        lambda: (lambda topic, summary: "sim"))
    asyncio.run(app_module._run_quality_sample_cycle())  # não levanta
