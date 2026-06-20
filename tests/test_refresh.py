"""Testes da política de refresh de conhecimento (anti-dup com janela de freshness)."""

from datetime import datetime, timedelta, timezone

from src.storage import DatabaseManager, LearnedTopic, Session


def _db(tmp_path):
    return DatabaseManager(f"sqlite:///{tmp_path / 'r.db'}")


def test_topico_recente_conta_como_estudado(tmp_path):
    db = _db(tmp_path)
    db.save_learned_topic("Tópico Recente", "http://x/1", "resumo", "web_search")
    assert db.is_topic_studied("Tópico Recente") is True


def test_topico_inexistente(tmp_path):
    assert _db(tmp_path).is_topic_studied("Nunca Estudado") is False


def test_topico_antigo_libera_reestudo(tmp_path):
    db = _db(tmp_path)
    with Session(db.engine) as s:
        s.add(LearnedTopic(topic="Tópico Antigo", url="http://x/2", summary="r",
                           category="web_search",
                           studied_at=datetime.now(timezone.utc) - timedelta(days=40)))
        s.commit()
    # > RELEARN_DAYS (21) → não conta como estudado → pode re-estudar (refresh)
    assert db.is_topic_studied("Tópico Antigo") is False


def test_url_antiga_libera_reestudo(tmp_path):
    db = _db(tmp_path)
    with Session(db.engine) as s:
        s.add(LearnedTopic(topic="Doc Antigo", url="http://docs/old", summary="r",
                           category="official_doc",
                           studied_at=datetime.now(timezone.utc) - timedelta(days=40)))
        s.commit()
    assert db.is_url_studied("http://docs/old") is False
