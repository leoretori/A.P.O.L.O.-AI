"""Memória episódica/autobiográfica (M2, Épico 2.2): episódios datados +
recall temporal ('o que a gente fez ontem?'). Cobre parsing de frases de tempo,
persistência (DatabaseManager) e a orquestração da EpisodicMemory."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session as SASession

from src.storage import DatabaseManager
from src.storage_models import SessionMessage
from src.memory import EpisodicMemory
from src.memory.episodic import parse_when, _parse_episode, _to_local_naive, _default_summarize


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


# ── Consolidação "sono" (Épico 2.3) ───────────────────────────
def _seed_session(db, sid, when, n=4):
    with SASession(db.engine) as s:
        for i in range(n):
            m = SessionMessage(session_id=sid, role="user" if i % 2 == 0 else "assistant",
                               content=f"{sid} msg {i}")
            m.timestamp = when
            s.add(m)
        s.commit()


def test_sessions_pending_episode_filtra_por_inatividade_e_tamanho(db):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    recent = datetime.now(timezone.utc)
    _seed_session(db, "antiga", old, n=4)
    _seed_session(db, "recente", recent, n=4)
    _seed_session(db, "curta", old, n=2)          # poucas mensagens
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=180)
    pend = db.sessions_pending_episode(cutoff, min_messages=4)
    ids = {p["session_id"] for p in pend}
    assert ids == {"antiga"}                       # só a inativa e longa o bastante


def test_consolidate_transforma_conversas_encerradas_em_episodios(db):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    _seed_session(db, "antiga", old, n=4)
    _seed_session(db, "recente", datetime.now(timezone.utc), n=4)
    res = _em(db).consolidate(inactive_minutes=180)
    assert res["consolidated"] == 1
    assert db.get_episode_for_session("antiga") is not None
    assert db.get_episode_for_session("recente") is None


def test_consolidate_e_idempotente(db):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    _seed_session(db, "antiga", old, n=4)
    em = _em(db)
    assert em.consolidate(inactive_minutes=180)["consolidated"] == 1
    assert em.consolidate(inactive_minutes=180)["consolidated"] == 0   # já tem episódio


def test_consolidate_sem_db_e_seguro():
    assert EpisodicMemory(db=None).consolidate() == {"consolidated": 0, "titles": []}


def test_default_summarize_cede_gpu_ao_usuario(monkeypatch):
    """A consolidação ('sono') roda em thread de fundo e pode resumir até 10
    sessões numa rodada — sem ceder o GpuGate, seguraria o lock do motor e faria
    o chat do usuário esperar atrás dela (mesma classe de bug do flywheel/blind_eval)."""
    import src.runtime as rt
    calls = {"n": 0}

    class _FakeGate:
        def wait_for_idle_sync(self, *a, **k):
            calls["n"] += 1

    monkeypatch.setattr(rt, "gpu_gate", _FakeGate())
    monkeypatch.setattr(rt, "get_chat_model", lambda: "qwen-1.5b")
    monkeypatch.setattr("src.llm.chat_resilient",
                        lambda model, messages, keep_alive=None: "TÍTULO: x\nRESUMO: y")
    out = _default_summarize("qualquer prompt")
    assert calls["n"] == 1
    assert "TÍTULO" in out


def test_default_summarize_sem_gate_nao_quebra(monkeypatch):
    import src.runtime as rt
    monkeypatch.setattr(rt, "gpu_gate", None)
    monkeypatch.setattr(rt, "get_chat_model", lambda: "qwen-1.5b")
    monkeypatch.setattr("src.llm.chat_resilient",
                        lambda model, messages, keep_alive=None: "ok")
    assert _default_summarize("prompt") == "ok"


def test_to_local_naive_converte_utc_para_local_naive():
    utc = datetime(2026, 7, 5, 23, 30, tzinfo=timezone.utc)
    local = _to_local_naive(utc)
    assert local.tzinfo is None                    # naive, no frame de parse_when
    # e é o mesmo instante convertido para o fuso local
    assert local == utc.astimezone().replace(tzinfo=None)
    assert _to_local_naive(None) is None
    assert _to_local_naive("2026-07-05T10:00:00").tzinfo is None
