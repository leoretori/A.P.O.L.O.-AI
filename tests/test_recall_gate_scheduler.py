"""Gate de regressão do recall noturno (P2.6) — o ciclo agendado em app.py.
Mesmo padrão do dedup/qualidade (P2.4/P2.5)."""

import asyncio

import app as app_module


class _FakeDB:
    def __init__(self, topics=None):
        self._topics = topics or [f"Tópico {i}" for i in range(20)]

    def sample_topics_for_quality(self, n=15):
        return [{"id": i, "topic": t, "summary": "x"} for i, t in enumerate(self._topics[:n])]

    def add_notification(self, *a, **k):
        pass


class _FakeRag:
    def __init__(self, esquecidos=()):
        self._esquecidos = set(esquecidos)

    def recall(self, query, n_results=5):
        if query in self._esquecidos:
            return [{"title": "nada a ver"}]
        return [{"title": query}]


def test_run_recall_gate_cycle_sem_db_ou_rag_nao_levanta(monkeypatch):
    monkeypatch.setattr(app_module, "db", None)
    monkeypatch.setattr(app_module, "rag", _FakeRag())
    asyncio.run(app_module._run_recall_gate_cycle())

    monkeypatch.setattr(app_module, "db", _FakeDB())
    monkeypatch.setattr(app_module, "rag", None)
    asyncio.run(app_module._run_recall_gate_cycle())


def test_run_recall_gate_cycle_roda_de_ponta_a_ponta(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "db", _FakeDB())
    monkeypatch.setattr(app_module, "rag", _FakeRag())
    monkeypatch.setattr(app_module, "RECALL_GATE_TRUTH_PATH", str(tmp_path / "gt.json"))
    monkeypatch.setattr(app_module, "RECALL_GATE_HISTORY_PATH", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(app_module, "RECALL_GATE_N", 15)
    asyncio.run(app_module._run_recall_gate_cycle())

    from src.recall_calibration import read_recall_gate_history
    hist = read_recall_gate_history(tmp_path / "hist.jsonl")
    assert len(hist) == 1 and hist[0]["hits"] == hist[0]["n"]  # tudo achado (fake sem esquecidos)


def test_run_recall_gate_cycle_poucos_topicos_nao_derruba(monkeypatch, tmp_path):
    """freeze_ground_truth pode levantar ValueError (base pequena demais) —
    o ciclo tem que engolir isso como 'pulado', não derrubar o scheduler."""
    monkeypatch.setattr(app_module, "db", _FakeDB(topics=["A", "B"]))
    monkeypatch.setattr(app_module, "rag", _FakeRag())
    monkeypatch.setattr(app_module, "RECALL_GATE_TRUTH_PATH", str(tmp_path / "gt.json"))
    monkeypatch.setattr(app_module, "RECALL_GATE_HISTORY_PATH", str(tmp_path / "hist.jsonl"))
    asyncio.run(app_module._run_recall_gate_cycle())  # não levanta

    from src.recall_calibration import read_recall_gate_history
    assert read_recall_gate_history(tmp_path / "hist.jsonl") == []


def test_run_recall_gate_cycle_avisa_quando_hit_rate_baixo(monkeypatch, tmp_path):
    topics = [f"Tópico {i}" for i in range(20)]
    monkeypatch.setattr(app_module, "db", _FakeDB(topics=topics))
    monkeypatch.setattr(app_module, "rag", _FakeRag(esquecidos=topics))  # esquece TUDO
    monkeypatch.setattr(app_module, "RECALL_GATE_TRUTH_PATH", str(tmp_path / "gt.json"))
    monkeypatch.setattr(app_module, "RECALL_GATE_HISTORY_PATH", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(app_module, "RECALL_GATE_N", 15)

    avisos = []
    monkeypatch.setattr(app_module.db, "add_notification",
                        lambda msg, kind="info": avisos.append(msg))
    asyncio.run(app_module._run_recall_gate_cycle())
    assert any("degradado" in a for a in avisos)
