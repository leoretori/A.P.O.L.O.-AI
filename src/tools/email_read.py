"""Leitura de e-mail via IMAP com permissão (M6, Épico 6.3).

Ferramenta `email.recent` (scope email.read), ESTRITAMENTE read-only:
- abre a caixa com EXAMINE (readonly=True) → o servidor não deixa marcar \\Seen
  nem apagar nada; só lê;
- credenciais vêm do .env (IMAP_HOST/IMAP_USER/IMAP_PASS/IMAP_PORT), NUNCA do
  banco — o grant email.read só habilita a capacidade.

A camada de parsing (parse_message/_since) é pura e testável; a conexão IMAP é um
adaptador fino, injetável nos testes (parâmetro `connect`).
"""
from __future__ import annotations

import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

from src.tools.registry import Tool, register

MAX_EMAILS = 50
_SNIPPET_CHARS = 240


def _decode(raw: str) -> str:
    try:
        return str(make_header(decode_header(raw or "")))
    except Exception:
        return raw or ""


def _text_snippet(msg: email.message.Message) -> str:
    """Primeiro trecho de texto legível do e-mail (prefere text/plain)."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
                    "attachment" not in str(part.get("Content-Disposition", "")):
                body = _payload_text(part)
                if body:
                    break
    else:
        body = _payload_text(msg)
    return re.sub(r"\s+", " ", body).strip()[:_SNIPPET_CHARS]


def _payload_text(part: email.message.Message) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    except Exception:
        return ""


def parse_message(raw: bytes) -> dict:
    """RFC822 cru → {from, subject, date, snippet}. Puro, sem rede."""
    msg = email.message_from_bytes(raw)
    date_raw = msg.get("Date", "")
    try:
        date_iso = parsedate_to_datetime(date_raw).isoformat(timespec="minutes")
    except Exception:
        date_iso = date_raw
    return {
        "from": _decode(msg.get("From", "")),
        "subject": _decode(msg.get("Subject", "")) or "(sem assunto)",
        "date": date_iso,
        "snippet": _text_snippet(msg),
    }


def _since(phrase: str, now: datetime) -> datetime:
    """Data-limite (inclusive) para a busca IMAP SINCE."""
    p = (phrase or "").strip().lower()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if "ontem" in p:
        return day0 - timedelta(days=1)
    if "hoje" in p or not p:
        return day0
    if "semana" in p:
        return day0 - timedelta(days=7)
    m = re.search(r"(\d+)\s*d", p)                       # "7d", "30 dias"
    if m:
        return day0 - timedelta(days=int(m.group(1)))
    return day0


def _connect() -> imaplib.IMAP4:
    host = os.getenv("IMAP_HOST")
    user = os.getenv("IMAP_USER")
    pw = os.getenv("IMAP_PASS")
    if not (host and user and pw):
        raise RuntimeError(
            "e-mail não configurado — defina IMAP_HOST, IMAP_USER e IMAP_PASS no "
            ".env para o A.P.O.L.O. poder LER seus e-mails (somente leitura)")
    port = int(os.getenv("IMAP_PORT", "993"))
    M = imaplib.IMAP4_SSL(host, port)
    M.login(user, pw)
    return M


def _first_raw(fetch_data) -> bytes | None:
    """Extrai os bytes RFC822 do retorno esquisito do imaplib.fetch."""
    for part in fetch_data or []:
        if isinstance(part, tuple) and len(part) >= 2 and isinstance(part[1], (bytes, bytearray)):
            return bytes(part[1])
    return None


def fetch_recent(since_dt: datetime, limit: int = 20, connect=None) -> list[dict]:
    """Últimos e-mails desde `since_dt`, mais novos primeiro. READ-ONLY (EXAMINE).
    `connect` é injetável nos testes (fábrica de cliente IMAP)."""
    conn = connect or _connect
    M = conn()
    try:
        M.select("INBOX", readonly=True)                 # EXAMINE: nada é alterado
        typ, data = M.search(None, "SINCE", since_dt.strftime("%d-%b-%Y"))
        ids = data[0].split() if (data and data[0]) else []
        picked = ids[-limit:]
        out: list[dict] = []
        for num in reversed(picked):                     # mais novos primeiro
            typ, md = M.fetch(num, "(RFC822)")
            raw = _first_raw(md)
            if raw:
                out.append(parse_message(raw))
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _tool_recent(args: dict, ctx) -> dict:
    when = (args or {}).get("since", "hoje")
    limit = max(1, min(int((args or {}).get("limit", 20) or 20), MAX_EMAILS))
    since_dt = _since(when, datetime.now())
    emails = fetch_recent(since_dt, limit)
    return {"since": when, "count": len(emails), "emails": emails}


register(Tool(name="email.recent", scope="email.read",
              description="Lê os e-mails recentes da INBOX (IMAP, somente leitura)",
              handler=_tool_recent))
