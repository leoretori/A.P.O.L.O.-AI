"""Isolamento de falha entre ciclos noturnos do scheduler (item 5.1 do
PLANO_CEREBRO_ASSUME.md). `_maybe_run_daily` foi extraído do padrão
hora+data repetido 4x (dedup/qualidade/recall-gate/briefing — item 6.2,
regra dos 3): garante que uma falha NÃO PREVISTA num ciclo (algo que
escapasse do try/except interno de cada `_run_X_cycle`) não impede os
demais ciclos do mesmo tick de rodar."""

import asyncio
from datetime import date

import app as app_module


def _reset():
    app_module._last_cycle_dates.clear()


def test_maybe_run_daily_roda_quando_hora_bate():
    _reset()
    called = []

    async def cycle():
        called.append(1)

    asyncio.run(app_module._maybe_run_daily("x", 0, cycle))
    assert called == [1]
    assert app_module._last_cycle_dates["x"] == date.today()


def test_maybe_run_daily_nao_roda_2x_no_mesmo_dia():
    _reset()
    called = []

    async def cycle():
        called.append(1)

    async def run_twice():
        await app_module._maybe_run_daily("x", 0, cycle)
        await app_module._maybe_run_daily("x", 0, cycle)

    asyncio.run(run_twice())
    assert called == [1]


def test_maybe_run_daily_hora_desligada_nunca_roda():
    _reset()
    called = []

    async def cycle():
        called.append(1)

    asyncio.run(app_module._maybe_run_daily("x", -1, cycle))
    assert called == []
    assert "x" not in app_module._last_cycle_dates


def test_falha_de_um_ciclo_nao_impede_os_outros_no_mesmo_tick():
    """O achado central do item 5.1: um ciclo que estoura uma exceção NÃO
    PREVISTA (bug que escaparia do try/except interno de `_run_X_cycle`)
    não pode travar os ciclos seguintes do mesmo tick do scheduler."""
    _reset()
    called = []

    async def falha():
        raise RuntimeError("bug nao previsto, escapou do try/except interno")

    async def ok_a():
        called.append("a")

    async def ok_b():
        called.append("b")

    async def tick():
        await app_module._maybe_run_daily("falha", 0, falha)
        await app_module._maybe_run_daily("a", 0, ok_a)
        await app_module._maybe_run_daily("b", 0, ok_b)

    asyncio.run(tick())  # não levanta — a falha vira log, não propaga
    assert called == ["a", "b"]
    # a data do ciclo que falhou também foi marcada — não fica retentando
    # sem parar no mesmo dia, mesma disciplina do flywheel/dedup/etc.
    assert app_module._last_cycle_dates["falha"] == date.today()


def test_run_briefing_cycle_chama_build_briefing(monkeypatch):
    sent = {}

    def fake_build_briefing(db, episodic, learner, profile, hours):
        return {"text": "resumo do dia"}

    class _FakeDB:
        def add_notification(self, text, kind=""):
            sent["text"], sent["kind"] = text, kind

    monkeypatch.setattr(app_module, "db", _FakeDB())
    monkeypatch.setattr("src.briefing.build_briefing", fake_build_briefing)
    asyncio.run(app_module._run_briefing_cycle())
    assert "resumo do dia" in sent["text"]
    assert sent["kind"] == "briefing"
