"""Repetição espaçada — storage + recall ativo do learner (M8, Épico 8.1)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.learner import LearningEngine
from src.storage import DatabaseManager


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/rev.db")


# ── Storage ───────────────────────────────────────────────────
def test_upsert_get_due(db):
    now = datetime.now(timezone.utc)
    db.upsert_review("Redis", 2.5, 1, 1, 0, now - timedelta(days=1), now)
    db.upsert_review("Kafka", 2.5, 6, 2, 0, now + timedelta(days=5), now)
    assert db.get_review("Redis")["reps"] == 1
    due = [r["topic"] for r in db.due_reviews(now, 10)]
    assert due == ["Redis"]                       # só o vencido
    assert db.count_reviews() == 2


def test_upsert_atualiza_no_lugar(db):
    now = datetime.now(timezone.utc)
    db.upsert_review("X", 2.5, 1, 1, 0, now, now)
    db.upsert_review("X", 2.6, 6, 2, 0, now, now)
    assert db.count_reviews() == 1 and db.get_review("X")["interval"] == 6


# ── Learner: auto-teste + re-enfileiramento ───────────────────
def _bare_engine(db, rag):
    eng = LearningEngine.__new__(LearningEngine)
    eng.db = db
    eng.rag = rag
    eng._self_queue = asyncio.Queue(maxsize=24)
    eng._next_studies = []
    return eng


def test_recall_strength_do_rag():
    class _RAG:
        def recall(self, t, n): return [{"relevance": 0.9}] if t == "sei" else []
    eng = _bare_engine(None, _RAG())
    assert eng._recall_strength("sei") == (0.9, True)
    assert eng._recall_strength("nao_sei") == (0.0, False)


def test_active_recall_reenfileira_esquecidos(db):
    past = datetime.now(timezone.utc) - timedelta(days=1)
    db.upsert_review("Esquecido", 2.5, 1, 1, 0, past, past)
    db.upsert_review("Lembrado", 2.5, 1, 1, 0, past, past)

    class _RAG:
        def recall(self, topic, n):
            return [{"relevance": 0.9}] if topic == "Lembrado" else []   # esqueceu o outro

    eng = _bare_engine(db, _RAG())
    asyncio.run(eng._run_active_recall(limit=10))

    fila = []
    while not eng._self_queue.empty():
        fila.append(eng._self_queue.get_nowait())
    assert "Esquecido" in fila and "Lembrado" not in fila     # só o esquecido volta
    # o lembrado avançou (reps 1→2 → intervalo 6); o esquecido resetou + lapso
    assert db.get_review("Lembrado")["interval"] == 6
    assert db.get_review("Esquecido")["interval"] == 1
    assert db.get_review("Esquecido")["lapses"] == 1


def test_ensure_review_scheduled_nao_sobrescreve(db):
    async def run():
        await db_to_thread_ensure(eng, "Tópico A")          # cria
        first = db.get_review("Tópico A")
        # marca como avançado; segundo save NÃO deve resetar
        db.upsert_review("Tópico A", 2.6, 6, 2, 0,
                         datetime.now(timezone.utc), datetime.now(timezone.utc))
        await db_to_thread_ensure(eng, "Tópico A")          # já existe → no-op
        return db.get_review("Tópico A")

    eng = _bare_engine(db, None)

    async def db_to_thread_ensure(engine, topic):
        await engine._ensure_review_scheduled(topic)

    out = asyncio.run(run())
    assert out["interval"] == 6 and out["reps"] == 2         # preservado


def test_endpoint_reviews(tmp_path):
    from fastapi.testclient import TestClient

    from app import app
    from src import runtime as rt

    prev = rt.db
    rt.db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/ep.db")
    now = datetime.now(timezone.utc)
    rt.db.upsert_review("A", 2.5, 1, 1, 0, now - timedelta(days=1), now)
    rt.db.upsert_review("B", 2.5, 6, 2, 0, now + timedelta(days=5), now)
    try:
        d = TestClient(app).get("/api/learning/reviews").json()
        assert d["total"] == 2 and d["due"] == 1 and d["due_topics"] == ["A"]
    finally:
        rt.db = prev
