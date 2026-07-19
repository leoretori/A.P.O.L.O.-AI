"""Testes da lógica de aprendizado/dados em storage.py que faltava cobertura:
anti-duplicação, dedup, timeline, toggle de agendamento.
"""

import pytest

from src.storage import DatabaseManager


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/test.db")


# ── is_url_studied / is_topic_studied ────────────────────────────
def test_is_url_studied(db):
    assert db.is_url_studied("https://x/y") is False
    db.save_learned_topic("Tópico A", "https://x/y", "resumo")
    assert db.is_url_studied("https://x/y") is True
    assert db.is_url_studied("https://outra/url") is False


def test_is_topic_studied(db):
    assert db.is_topic_studied("Redis") is False
    db.save_learned_topic("Redis", "https://r/1", "resumo")
    assert db.is_topic_studied("Redis") is True


def test_is_topic_studied_vazio_eh_falso(db):
    assert db.is_topic_studied("") is False


# ── count_topic_duplicates / dedup_learned_topics ────────────────
def test_count_duplicates_zero_sem_repeticao(db):
    db.save_learned_topic("A", "u1", "s")
    db.save_learned_topic("B", "u2", "s")
    assert db.count_topic_duplicates() == 0


def test_count_e_dedup_de_reestudos(db):
    # "A" estudado 3x (2 excedentes), "B" 1x.
    db.save_learned_topic("A", "u1", "s")
    db.save_learned_topic("A", "u2", "s")
    db.save_learned_topic("A", "u3", "s")
    db.save_learned_topic("B", "u4", "s")
    assert db.count_topic_duplicates() == 2
    removed = db.dedup_learned_topics()
    assert removed == 2
    assert db.count_topic_duplicates() == 0
    # Sobrou um registro de cada tópico.
    topics = {r["topic"] for r in db.get_learning_history(limit=50)}
    assert topics == {"A", "B"}


def test_dedup_sem_duplicatas_remove_zero(db):
    db.save_learned_topic("Único", "u1", "s")
    assert db.dedup_learned_topics() == 0


def test_dedup_ignora_caixa_e_espacos(db):
    db.save_learned_topic("Kubernetes", "u1", "s")
    db.save_learned_topic("  kubernetes ", "u2", "s")  # mesmo tópico, caixa/espaço diferentes
    assert db.dedup_learned_topics() == 1


# ── scan_learned_topics_junk (item 4 das melhorias de 2026-07-19: faxina
# retroativa de tópicos degenerados, mesmo portão do content_hygiene) ──
def test_scan_learned_topics_junk_acha_degenerado_poupa_legitimo(db):
    db.save_learned_topic("Kubernetes autoscaling best practices", "u1", "s")
    db.save_learned_topic("Neurobiologia urburation/urbanatura da arte futura", "u2", "s")
    junk = db.scan_learned_topics_junk()
    assert len(junk) == 1
    assert "urburation" in junk[0]["topic"]
    assert junk[0]["url"] == "u2"


def test_scan_learned_topics_junk_vazio_quando_tudo_limpo(db):
    db.save_learned_topic("Redis pub/sub patterns", "u1", "s")
    assert db.scan_learned_topics_junk() == []


# ── get_learning_history sem repetição ───────────────────────────
def test_history_nao_repete_topico(db):
    db.save_learned_topic("A", "u1", "s")
    db.save_learned_topic("A", "u2", "s")
    hist = db.get_learning_history(limit=10)
    assert [h["topic"] for h in hist].count("A") == 1


# ── get_learning_timeline ────────────────────────────────────────
def test_timeline_tem_um_ponto_por_dia(db):
    tl = db.get_learning_timeline(days=7)
    assert len(tl) == 7
    assert all("date" in p and "count" in p for p in tl)
    # Sem nada estudado → todos zero.
    assert all(p["count"] == 0 for p in tl)


def test_timeline_conta_topicos_unicos_de_hoje(db):
    db.save_learned_topic("A", "u1", "s")
    db.save_learned_topic("A", "u2", "s")   # re-estudo: não conta de novo
    db.save_learned_topic("B", "u3", "s")
    tl = db.get_learning_timeline(days=3)
    hoje = tl[-1]  # o último ponto é hoje
    assert hoje["count"] == 2  # A e B (não 3)


# ── toggle_schedule ──────────────────────────────────────────────
def test_toggle_schedule_alterna_enabled(db):
    row = db.add_schedule("estudar redis", "08:00")
    sid = row["id"]
    assert row["enabled"] is True
    assert db.toggle_schedule(sid) is True
    assert db.list_schedules()[0]["enabled"] is False
    assert db.toggle_schedule(sid) is True
    assert db.list_schedules()[0]["enabled"] is True


def test_toggle_schedule_inexistente(db):
    assert db.toggle_schedule(9999) is False


# ── verified (P2.1) ────────────────────────────────────────────
def test_save_learned_topic_grava_verified(db):
    db.save_learned_topic("A", "u1", "s", verified="verified")
    db.save_learned_topic("B", "u2", "s", verified="failed")
    db.save_learned_topic("C", "u3", "s")  # sem amostrar → None
    hist = {r["topic"]: r["verified"] for r in db.get_learning_history(limit=10)}
    assert hist["A"] == "verified"
    assert hist["B"] == "failed"
    assert hist["C"] is None


def test_get_verification_stats(db):
    db.save_learned_topic("A", "u1", "s", verified="verified")
    db.save_learned_topic("B", "u2", "s", verified="verified")
    db.save_learned_topic("C", "u3", "s", verified="failed")
    db.save_learned_topic("D", "u4", "s")  # não amostrado
    stats = db.get_verification_stats()
    assert stats == {
        "total": 4, "sampled": 3, "verified": 2, "failed": 1,
        "pct_sampled": 75, "pct_faithful_of_sampled": 67,
    }


def test_get_verification_stats_vazio(db):
    assert db.get_verification_stats() == {
        "total": 0, "sampled": 0, "verified": 0, "failed": 0,
        "pct_sampled": None, "pct_faithful_of_sampled": None,
    }


# ── sample_topics_for_quality (P2.5) ────────────────────────────
def test_sample_topics_for_quality_traz_topico_e_resumo(db):
    db.save_learned_topic("A", "u1", "resumo de A")
    db.save_learned_topic("B", "u2", "resumo de B")
    amostra = db.sample_topics_for_quality(n=10)
    assert len(amostra) == 2
    assert {a["topic"] for a in amostra} == {"A", "B"}
    assert all(set(a.keys()) == {"id", "topic", "summary"} for a in amostra)


def test_sample_topics_for_quality_respeita_o_limite(db):
    for i in range(20):
        db.save_learned_topic(f"T{i}", f"u{i}", f"resumo {i}")
    assert len(db.sample_topics_for_quality(n=5)) == 5


def test_sample_topics_for_quality_ignora_sem_resumo(db):
    db.save_learned_topic("Com resumo", "u1", "conteúdo real")
    db.save_learned_topic("Sem resumo", "u2", "")
    amostra = db.sample_topics_for_quality(n=10)
    assert [a["topic"] for a in amostra] == ["Com resumo"]


def test_sample_topics_for_quality_vazio(db):
    assert db.sample_topics_for_quality(n=10) == []


# ── relearn_days por tópico (P2.7) ──────────────────────────────
def _envelhecer(db, topic: str, dias: int) -> None:
    """Empurra `studied_at` pro passado — só pra controlar o teste, não é API
    pública do projeto."""
    from datetime import timedelta

    from sqlalchemy.orm import Session

    from src.storage_models import LearnedTopic, _now

    with Session(db.engine) as s:
        row = s.query(LearnedTopic).filter(LearnedTopic.topic == topic).first()
        row.studied_at = _now() - timedelta(days=dias)
        s.commit()


def test_is_topic_studied_respeita_relearn_days_customizado(db):
    db.save_learned_topic("Kubernetes", "u1", "s")
    _envelhecer(db, "Kubernetes", dias=8)
    # janela padrão (21d): ainda "estudado" — 8 dias é recente demais pra liberar.
    assert db.is_topic_studied("Kubernetes") is True
    # janela curta (5d, ex.: setor volátil): já passou — livre pra re-estudar.
    assert db.is_topic_studied("Kubernetes", relearn_days=5) is False
    # janela mais longa que 8d ainda segura.
    assert db.is_topic_studied("Kubernetes", relearn_days=10) is True


def test_is_url_studied_respeita_relearn_days_customizado(db):
    db.save_learned_topic("Kubernetes", "https://k8s", "s")
    _envelhecer(db, "Kubernetes", dias=8)
    assert db.is_url_studied("https://k8s") is True
    assert db.is_url_studied("https://k8s", relearn_days=5) is False
