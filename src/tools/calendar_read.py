"""Leitura de agenda (.ics) com permissão (M6, Épico 6.3).

Ferramenta `calendar.events` (scope calendar.read), read-only: lê um arquivo
iCalendar (.ics) cujo caminho o usuário autoriza na note do grant e responde
"o que tenho hoje/amanhã/esta semana". Parser próprio, determinístico e sem
dependência externa — testável sem rede nem servidor.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.tools.registry import Tool, register

_DATE = re.compile(r"^\d{8}$")
_DATETIME = re.compile(r"^(\d{8}T\d{6})(Z)?$")


def _unfold(text: str) -> list[str]:
    """RFC 5545: linhas continuadas começam com espaço/tab — junta na anterior."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _parse_dt(val: str) -> tuple[datetime | None, bool]:
    """Devolve (datetime_naive_local, all_day). Formas: YYYYMMDD (dia inteiro),
    YYYYMMDDTHHMMSS (flutuante/local) e ...Z (UTC → convertido p/ local)."""
    val = (val or "").strip()
    if _DATE.match(val):
        return datetime.strptime(val, "%Y%m%d"), True
    m = _DATETIME.match(val)
    if m:
        dt = datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
        if m.group(2):  # sufixo Z = UTC → hora local naive
            dt = dt.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return dt, False
    return None, False


def parse_ics(text: str) -> list[dict]:
    """Extrai VEVENTs → [{summary, start, end, location, all_day}] (start/end
    são datetime naive locais). Ignora eventos sem DTSTART válido."""
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(text or ""):
        s = line.strip()
        if s == "BEGIN:VEVENT":
            cur = {"summary": "", "location": "", "start": None,
                   "end": None, "all_day": False}
            continue
        if s == "END:VEVENT":
            if cur and cur["start"] is not None:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in s:
            continue
        name, value = s.split(":", 1)
        key = name.split(";", 1)[0].upper()      # descarta params (TZID, VALUE...)
        if key == "SUMMARY":
            cur["summary"] = value.strip()
        elif key == "LOCATION":
            cur["location"] = value.strip()
        elif key == "DTSTART":
            dt, allday = _parse_dt(value)
            cur["start"], cur["all_day"] = dt, allday
        elif key == "DTEND":
            dt, _ = _parse_dt(value)
            cur["end"] = dt
    return events


def window_for(phrase: str, now: datetime) -> tuple[datetime, datetime]:
    """Traduz 'hoje'/'amanhã'/'esta semana'/'próxima semana' numa janela
    [início, fim). Vazio/desconhecido → hoje."""
    p = (phrase or "").strip().lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "amanh" in p:                                   # amanhã / amanha
        s = day0 + timedelta(days=1)
        return s, s + timedelta(days=1)
    if "semana" in p:
        if "prox" in p or "próx" in p:
            s = day0 + timedelta(days=7)
            return s, s + timedelta(days=7)
        return day0, day0 + timedelta(days=7)
    if "hoje" in p or not p:
        return day0, day0 + timedelta(days=1)
    return day0, day0 + timedelta(days=7)              # default: próximos 7 dias


def _event_end(ev: dict) -> datetime:
    if ev.get("end"):
        return ev["end"]
    # sem DTEND: dia inteiro dura o dia; evento com hora, ~1h
    return ev["start"] + (timedelta(days=1) if ev["all_day"] else timedelta(hours=1))


def events_in_window(events: list[dict], start: datetime, end: datetime) -> list[dict]:
    """Eventos que se sobrepõem a [start, end), ordenados por início."""
    hits = [e for e in events
            if e["start"] < end and _event_end(e) > start]
    return sorted(hits, key=lambda e: e["start"])


def _ev_dict(e: dict) -> dict:
    return {"summary": e["summary"] or "(sem título)",
            "start": e["start"].isoformat(timespec="minutes"),
            "end": _event_end(e).isoformat(timespec="minutes"),
            "location": e["location"], "all_day": e["all_day"]}


def _tool_events(args: dict, ctx) -> dict:
    path = (getattr(ctx, "note", "") or "").strip().strip('"').strip("'")
    if not path:
        raise PermissionError(
            "nenhum calendário configurado — abra 🔐 Permissões, autorize "
            "'calendar.read' e informe o arquivo .ics")
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"arquivo .ics não encontrado: {path}")
    events = parse_ics(p.read_text(encoding="utf-8", errors="replace"))
    when = (args or {}).get("when", "")
    ws, we = window_for(when, datetime.now())
    hits = events_in_window(events, ws, we)
    return {"when": when or "hoje", "count": len(hits),
            "events": [_ev_dict(e) for e in hits]}


register(Tool(name="calendar.events", scope="calendar.read",
              description="Lista eventos da agenda (.ics) no período pedido",
              handler=_tool_events))
