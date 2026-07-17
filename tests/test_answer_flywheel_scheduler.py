"""Disparo do flywheel de resposta no scheduler (item 2 do
PLANO_FLYWHEEL_AUTOMATICO.md) — mesma disciplina de isolamento do resto."""

import asyncio

import app as app_module


def test_run_answer_flywheel_cycle_pulado_nao_levanta(monkeypatch):
    """Sem dataset/checkpoint reais neste teste, run_answer_flywheel real
    pula com 'skipped' — o ciclo não deve derrubar o scheduler."""
    app_module.db = None
    asyncio.run(app_module._run_answer_flywheel_cycle())  # não levanta


def test_run_answer_flywheel_cycle_promovido_notifica(monkeypatch):
    sent = {}

    class _FakeDB:
        def add_notification(self, text, kind=""):
            sent["text"], sent["kind"] = text, kind

    def fake_run_answer_flywheel(db, **kw):
        return {"status": "promoted", "incumbent_win_rate": 33.3,
                "candidate_win_rate": 50.0, "n_questions": 15}

    app_module.db = _FakeDB()
    monkeypatch.setattr("src.nanollm.flywheel.run_answer_flywheel", fake_run_answer_flywheel)
    asyncio.run(app_module._run_answer_flywheel_cycle())
    assert "33.3" in sent["text"] and "50.0" in sent["text"]
    assert sent["kind"] == "info"


def test_run_answer_flywheel_cycle_erro_nao_derruba_scheduler(monkeypatch):
    class _FakeDB:
        def add_notification(self, *a, **k):
            pass

    def _raise(db, **kw):
        raise RuntimeError("professor fora do ar")

    app_module.db = _FakeDB()
    monkeypatch.setattr("src.nanollm.flywheel.run_answer_flywheel", _raise)
    asyncio.run(app_module._run_answer_flywheel_cycle())  # não levanta
