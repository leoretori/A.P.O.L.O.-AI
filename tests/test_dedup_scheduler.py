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
    def __init__(self, pruned=0, raise_=False, junk=None):
        self._pruned = pruned
        self._raise = raise_
        self._junk = junk or []
        self.deleted_ids = []

    def dedup_learned_topics(self):
        if self._raise:
            raise RuntimeError("sqlite locked")
        return self._pruned

    def scan_learned_topics_junk(self):
        return self._junk

    def delete_learned_topic(self, topic_id):
        self.deleted_ids.append(topic_id)
        for j in self._junk:
            if j["id"] == topic_id:
                return {"topic": j["topic"], "url": j["url"]}
        return None


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


# ── item 4 das melhorias de 2026-07-19: faxina noturna de degenerados ──
def test_run_dedup_cycle_remove_topicos_degenerados(monkeypatch):
    junk = [{"id": 1, "topic": "urburation/urbanatura da arte", "url": "u1"},
           {"id": 2, "topic": "Síntese #24 (ou qualquer síndrome específica)", "url": "u2"}]
    fake_db = _FakeDB(junk=junk)
    monkeypatch.setattr(app_module, "rag", None)
    monkeypatch.setattr(app_module, "db", fake_db)
    monkeypatch.setattr(app_module, "knowledge_db", None)
    asyncio.run(app_module._run_dedup_cycle())
    assert sorted(fake_db.deleted_ids) == [1, 2]


def test_run_dedup_cycle_propaga_remocao_para_knowledge_db_e_rag(monkeypatch):
    junk = [{"id": 5, "topic": "urburation/urbanatura", "url": "http://x"}]
    fake_db = _FakeDB(junk=junk)
    forgotten = {}

    class _FakeKnowledgeDB:
        def delete_by_url(self, url):
            forgotten["url"] = url
            return 1

    class _FakeRagForget:
        def dedup_exact(self):
            return 0

        def forget_topic(self, topic):
            forgotten["topic"] = topic
            return 1

    monkeypatch.setattr(app_module, "rag", _FakeRagForget())
    monkeypatch.setattr(app_module, "db", fake_db)
    monkeypatch.setattr(app_module, "knowledge_db", _FakeKnowledgeDB())
    asyncio.run(app_module._run_dedup_cycle())
    assert forgotten == {"url": "http://x", "topic": "urburation/urbanatura"}


def test_run_dedup_cycle_faxina_sem_lixo_nao_remove_nada(monkeypatch):
    fake_db = _FakeDB(junk=[])
    monkeypatch.setattr(app_module, "rag", None)
    monkeypatch.setattr(app_module, "db", fake_db)
    monkeypatch.setattr(app_module, "knowledge_db", None)
    asyncio.run(app_module._run_dedup_cycle())
    assert fake_db.deleted_ids == []


def test_run_dedup_cycle_faxina_falha_nao_derruba(monkeypatch):
    class _DBQuebrado(_FakeDB):
        def scan_learned_topics_junk(self):
            raise RuntimeError("banco indisponível")

    monkeypatch.setattr(app_module, "rag", None)
    monkeypatch.setattr(app_module, "db", _DBQuebrado())
    asyncio.run(app_module._run_dedup_cycle())  # não levanta
