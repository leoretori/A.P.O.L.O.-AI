"""Leitura de agenda .ics com permissão (M6, Épico 6.3).

Parser determinístico de iCalendar + janelas hoje/amanhã/semana, gated por
calendar.read (a note do grant é o caminho do .ics). Sem rede, sem servidor.
"""
from datetime import datetime, timedelta

import pytest

from src.storage import DatabaseManager
from src.tools import run_tool
from src.tools.calendar_read import (
    parse_ics, window_for, events_in_window,
)


def _ics(events: str) -> str:
    return "BEGIN:VCALENDAR\nVERSION:2.0\n" + events + "END:VCALENDAR\n"


def _vevent(summary, dtstart, dtend=None, location=None):
    s = f"BEGIN:VEVENT\nSUMMARY:{summary}\nDTSTART:{dtstart}\n"
    if dtend:
        s += f"DTEND:{dtend}\n"
    if location:
        s += f"LOCATION:{location}\n"
    return s + "END:VEVENT\n"


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/tools.db")


# ── Parser ────────────────────────────────────────────────────
def test_parse_datetime_e_all_day_e_location():
    ics = _ics(
        _vevent("Reunião", "20260115T140000", "20260115T150000", "Sala 3")
        + _vevent("Feriado", "20260116")     # dia inteiro (só data)
    )
    evs = parse_ics(ics)
    assert len(evs) == 2
    reun = next(e for e in evs if e["summary"] == "Reunião")
    assert reun["all_day"] is False and reun["location"] == "Sala 3"
    assert reun["start"] == datetime(2026, 1, 15, 14, 0)
    fer = next(e for e in evs if e["summary"] == "Feriado")
    assert fer["all_day"] is True and fer["start"] == datetime(2026, 1, 16)


def test_parse_desdobra_linhas_continuadas():
    """SUMMARY longo quebrado em duas linhas (continuação começa com espaço)."""
    ics = _ics("BEGIN:VEVENT\nSUMMARY:Título muito\n  comprido aqui\n"
               "DTSTART:20260101T090000\nEND:VEVENT\n")
    evs = parse_ics(ics)
    assert evs[0]["summary"] == "Título muito comprido aqui"


def test_evento_sem_dtstart_e_ignorado():
    ics = _ics("BEGIN:VEVENT\nSUMMARY:Incompleto\nEND:VEVENT\n"
               + _vevent("Válido", "20260101T090000"))
    assert [e["summary"] for e in parse_ics(ics)] == ["Válido"]


# ── Janelas temporais ─────────────────────────────────────────
def test_window_hoje_amanha_semana():
    now = datetime(2026, 1, 15, 10, 0)
    h0, h1 = window_for("hoje", now)
    assert h0 == datetime(2026, 1, 15) and h1 == datetime(2026, 1, 16)
    a0, a1 = window_for("amanhã", now)
    assert a0 == datetime(2026, 1, 16) and a1 == datetime(2026, 1, 17)
    s0, s1 = window_for("esta semana", now)
    assert (s1 - s0) == timedelta(days=7)
    p0, _ = window_for("próxima semana", now)
    assert p0 == datetime(2026, 1, 22)


def test_events_in_window_filtra_e_ordena():
    evs = parse_ics(_ics(
        _vevent("Tarde", "20260115T150000", "20260115T160000")
        + _vevent("Manhã", "20260115T090000", "20260115T100000")
        + _vevent("Outro dia", "20260120T090000")
    ))
    hits = events_in_window(evs, datetime(2026, 1, 15), datetime(2026, 1, 16))
    assert [e["summary"] for e in hits] == ["Manhã", "Tarde"]   # ordenado por início


# ── Via run_tool: porteira + agenda ───────────────────────────
def test_calendar_negado_sem_grant(db, tmp_path):
    ics = tmp_path / "agenda.ics"
    ics.write_text(_ics(_vevent("X", "20260101T090000")), encoding="utf-8")
    r = run_tool("calendar.events", {"when": "hoje"}, db)
    assert r["ok"] is False and r.get("denied") is True and r["scope"] == "calendar.read"


def test_calendar_le_eventos_de_amanha(db, tmp_path):
    now = datetime.now()
    amanha = (now + timedelta(days=1)).strftime("%Y%m%d")
    ics = tmp_path / "agenda.ics"
    ics.write_text(_ics(
        _vevent("Dentista", amanha + "T140000", amanha + "T150000", "Clínica")
        + _vevent("Hoje só", now.strftime("%Y%m%d") + "T090000")
    ), encoding="utf-8")
    db.grant_permission("calendar.read", note=str(ics))
    r = run_tool("calendar.events", {"when": "amanhã"}, db)
    assert r["ok"] is True
    assert r["result"]["count"] == 1
    assert r["result"]["events"][0]["summary"] == "Dentista"
    assert r["result"]["events"][0]["location"] == "Clínica"


def test_calendar_sem_arquivo_configurado(db):
    db.grant_permission("calendar.read")     # sem note (sem .ics)
    r = run_tool("calendar.events", {"when": "hoje"}, db)
    assert r["ok"] is False and "nenhum calendário configurado" in r["error"]
