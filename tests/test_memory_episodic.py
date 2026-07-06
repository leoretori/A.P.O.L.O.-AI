"""Memória episódica/autobiográfica (M2, Épico 2.2): episódios datados +
recall temporal ('o que a gente fez ontem?'). Cobre parsing de frases de tempo,
persistência (DatabaseManager) e a orquestração da EpisodicMemory."""
from datetime import datetime, timedelta

import pytest

from src.storage import DatabaseManager
from src.memory import EpisodicMemory
from src.memory.episodic import parse_when, _parse_episode


NOW = datetime(2026, 7, 6, 12, 0)   # segunda-feira


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/ep.db")


def _em(db, title="fechamos o épico", resumo="unificamos o recall"):
    return EpisodicMemory(db=db, summarize_fn=lambda p: f"TÍTULO: {title}\nRESUMO: {resumo}")


MSGS = [
    {"role": "user", "content": "vamos fechar o épico"},
    {"role": "assistant", "content": "ok, começando"},
    {"role": "user", "content": "migra o chat"},
    {"role": "assistant", "content": "feito e testado"},
]


# ── parse_when (tradução de frases temporais) ─────────────────
def test_parse_when_ontem():
    start, end = parse_when("o que fizemos ontem?", NOW)
    assert start == datetime(2026, 7, 5) and end == datetime(2026, 7, 6)


def test_parse_when_hoje():
    start, end = parse_when("o que rolou hoje", NOW)
    assert start == datetime(2026, 7, 6) and end == datetime(2026, 7, 7)


def test_parse_when_anteontem():
    start, end = parse_when("anteontem", NOW)
    assert start == datetime(2026, 7, 4) and end == datetime(2026, 7, 5)


def test_parse_when_semana_passada():
    # NOW é segunda 2026-07-06 → semana passada = seg 2026-06-29 a seg 2026-07-06
    start, end = parse_when("semana passada", NOW)
    assert start == datetime(2026, 6, 29) and end == datetime(2026, 7, 6)


def test_parse_when_n_dias():
    start, end = parse_when("nos últimos 7 dias", NOW)
    assert start == datetime(2026, 6, 29) and end == datetime(2026, 7, 7)


def test_parse_when_nao_temporal_retorna_none():
    assert parse_when("como funciona o asyncio?", NOW) is None


# ── _parse_episode (extração TÍTULO/RESUMO) ───────────────────
def test_parse_episode_formato_correto():
    t, s = _parse_episode("TÍTULO: fechamos o painel\nRESUMO: feed unificado de 24h")
    assert t == "fechamos o painel" and s == "feed unificado de 24h"


def test_parse_episode_fallback_sem_formato():
    t, s = _parse_episode("só uma linha solta sobre o dia")
    assert t.startswith("só uma linha") and s == ""


# ── Persistência (DatabaseManager) ────────────────────────────
def test_save_episode_e_recall_between(db):
    db.save_episode("dia 5", session_id="s1", occurred_at=datetime(2026, 7, 5, 9))
    db.save_episode("dia 6", session_id="s2", occurred_at=datetime(2026, 7, 6, 9))
    only5 = db.get_episodes_between(datetime(2026, 7, 5), datetime(2026, 7, 6))
    assert [e["title"] for e in only5] == ["dia 5"]


def test_save_episode_dedup_por_sessao(db):
    db.save_episode("v1", session_id="s1")
    db.save_episode("v2", session_id="s1")     # mesma sessão → atualiza
    assert len(db.recent_episodes()) == 1
    assert db.get_episode_for_session("s1")["title"] == "v2"


def test_search_episodes(db):
    db.save_episode("fechamos o MemoryFabric", summary="porta única")
    db.save_episode("bug de boot", summary="ordem dos scripts")
    hits = db.search_episodes("memoryfabric")
    assert len(hits) == 1 and "MemoryFabric" in hits[0]["title"]


# ── EpisodicMemory (orquestração) ─────────────────────────────
def test_record_resume_e_persiste(db):
    ep = _em(db).record("s1", MSGS, occurred_at=datetime(2026, 7, 5, 10))
    assert ep["title"] == "fechamos o épico"
    saved = db.get_episode_for_session("s1")
    assert saved["summary"] == "unificamos o recall"


def test_record_ignora_conversa_curta(db):
    assert _em(db).record("s1", MSGS[:2]) is None   # < MIN_MESSAGES
    assert db.recent_episodes() == []


def test_recall_phrase_temporal(db):
    em = _em(db)
    em.record("s1", MSGS, occurred_at=datetime(2026, 7, 5, 10))    # ontem
    em.record("s2", MSGS, occurred_at=datetime(2026, 6, 20, 10))   # semana(s) atrás
    got = em.recall_phrase("o que fizemos ontem?", now=NOW)
    assert len(got) == 1 and got[0]["occurred_at"].startswith("2026-07-05")


def test_recall_phrase_nao_temporal_retorna_none(db):
    assert _em(db).recall_phrase("qual a capital da França?", now=NOW) is None


def test_record_sem_db_e_seguro():
    assert EpisodicMemory(db=None).record("s1", MSGS) is None
