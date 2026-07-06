"""Lembretes/follow-ups (M4, Épico 4.2): extração determinística de 'me lembra
de X' em conversas + persistência + resurface. Sem LLM."""
from datetime import datetime, timedelta

import pytest

from src.storage import DatabaseManager
from src.reminders import extract_reminders, _parse_due


NOW = datetime(2026, 7, 6, 8, 0)   # segunda, 8h


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/rem.db")


# ── Extração ──────────────────────────────────────────────────
def test_extrai_lembrete_simples():
    r = extract_reminders("me lembra de revisar o PR", NOW)
    assert r == [{"text": "revisar o PR", "due_at": None}]


def test_extrai_lembrete_com_amanha():
    r = extract_reminders("me lembra de pagar a conta amanhã", NOW)
    assert r[0]["text"] == "pagar a conta amanhã"
    assert r[0]["due_at"] == datetime(2026, 7, 7, 9, 0)


def test_extrai_variante_lembrete_dois_pontos():
    assert extract_reminders("lembrete: comprar leite")[0]["text"] == "comprar leite"


def test_extrai_variante_nao_deixa_esquecer():
    r = extract_reminders("não me deixa esquecer de ligar pro médico daqui a 2 dias", NOW)
    assert r[0]["text"] == "ligar pro médico daqui a 2 dias"
    assert r[0]["due_at"] == datetime(2026, 7, 8, 9, 0)


def test_nao_casa_lembranca_nem_pergunta():
    assert extract_reminders("tenho boas lembranças disso") == []
    assert extract_reminders("qual a capital da França?") == []
    assert extract_reminders("") == []


def test_corta_na_quebra_de_frase():
    r = extract_reminders("me lembra de estudar rust. e mais nada.", NOW)
    assert r[0]["text"] == "estudar rust"


def test_parse_due_varias_formas():
    assert _parse_due("semana que vem", NOW) == datetime(2026, 7, 13, 9, 0)
    assert _parse_due("em 3 dias", NOW) == datetime(2026, 7, 9, 9, 0)
    assert _parse_due("daqui a 4 horas", NOW) == datetime(2026, 7, 6, 12, 0)
    assert _parse_due("sem data aqui", NOW) is None


def test_due_hoje_depende_da_hora():
    # antes das 9h → vence às 9h de hoje; depois → +2h
    assert _parse_due("hoje", datetime(2026, 7, 6, 7)) == datetime(2026, 7, 6, 9, 0)
    assert _parse_due("hoje", datetime(2026, 7, 6, 14)) == datetime(2026, 7, 6, 16, 0)


# ── Persistência ──────────────────────────────────────────────
def test_save_e_dedup_de_pendente(db):
    rid = db.save_reminder("revisar o PR")
    assert rid is not None
    assert db.save_reminder("revisar o PR") is None          # dup pendente → não duplica
    assert [r["text"] for r in db.list_reminders()] == ["revisar o PR"]


def test_due_reminders_so_vencidos_nao_avisados(db):
    passado = db.save_reminder("vencido", due_at=NOW - timedelta(hours=1))
    db.save_reminder("futuro", due_at=NOW + timedelta(days=1))
    db.save_reminder("sem data")
    due = db.due_reminders(now=NOW)
    assert [r["text"] for r in due] == ["vencido"]
    db.mark_reminder_notified(passado)
    assert db.due_reminders(now=NOW) == []                    # não re-avisa


def test_mark_done_sai_dos_pendentes(db):
    rid = db.save_reminder("tarefa")
    assert db.mark_reminder_done(rid) is True
    assert db.list_reminders() == []
    assert db.mark_reminder_done(99999) is False


def test_reminder_texto_curto_ignorado(db):
    assert db.save_reminder("x") is None
