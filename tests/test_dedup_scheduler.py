"""Dedup automático noturno (P2.4) — RAG (exato) + log de aprendizado, sem
ação manual do Curador. Mesmo padrão do flywheel/backup (M25.3/M11.2)."""

import asyncio

import app as app_module


class _FakeRag:
    def __init__(self, pruned=0, raise_=False):
        self._pruned = pruned
        self._raise = raise_

    def dedup_exact(self):
        if self._raise:
            raise RuntimeError("chroma fora do ar")
        return self._pruned


class _FakeDB:
    def __init__(self, pruned=0, raise_=False):
        self._pruned = pruned
        self._raise = raise_

    def dedup_learned_topics(self):
        if self._raise:
            raise RuntimeError("sqlite locked")
        return self._pruned


def test_run_dedup_cycle_chama_os_dois_destinos(monkeypatch):
    monkeypatch.setattr(app_module, "rag", _FakeRag(pruned=3))
    monkeypatch.setattr(app_module, "db", _FakeDB(pruned=2))
    asyncio.run(app_module._run_dedup_cycle())  # não levanta


def test_run_dedup_cycle_rag_falha_nao_impede_o_log(monkeypatch):
    calls = {"log": False}

    class _DB(_FakeDB):
        def dedup_learned_topics(self):
            calls["log"] = True
            return 1

    monkeypatch.setattr(app_module, "rag", _FakeRag(raise_=True))
    monkeypatch.setattr(app_module, "db", _DB())
    asyncio.run(app_module._run_dedup_cycle())
    assert calls["log"] is True  # o log rodou mesmo com o rag quebrado


def test_run_dedup_cycle_log_falha_nao_derruba(monkeypatch):
    monkeypatch.setattr(app_module, "rag", _FakeRag(pruned=1))
    monkeypatch.setattr(app_module, "db", _FakeDB(raise_=True))
    asyncio.run(app_module._run_dedup_cycle())  # não levanta


def test_run_dedup_cycle_sem_rag_nem_db(monkeypatch):
    monkeypatch.setattr(app_module, "rag", None)
    monkeypatch.setattr(app_module, "db", None)
    asyncio.run(app_module._run_dedup_cycle())  # não levanta
