"""Leitura de e-mail (IMAP) com permissão (M6, Épico 6.3).

Read-only por construção: EXAMINE (readonly=True) + credenciais só do .env. O
parsing é puro (testável com bytes canônicos); a conexão IMAP é injetada por um
fake, sem rede nem servidor real.
"""
from datetime import datetime
from email.message import EmailMessage

import pytest

import src.tools.email_read as em
from src.storage import DatabaseManager
from src.tools import run_tool


def _raw(frm, subject, body, date="Mon, 06 Jul 2026 09:30:00 +0000"):
    m = EmailMessage()
    m["From"] = frm
    m["Subject"] = subject
    m["Date"] = date
    m.set_content(body)
    return m.as_bytes()


class _FakeIMAP:
    """Mímica mínima de imaplib: registra que foi readonly e serve mensagens."""
    def __init__(self, messages):
        self._messages = messages            # {id_bytes: raw_bytes}
        self.select_readonly = None
        self.logged_out = False

    def select(self, mailbox, readonly=False):
        self.select_readonly = readonly
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        return ("OK", [b" ".join(self._messages.keys())])

    def fetch(self, num, spec):
        raw = self._messages[num]
        return ("OK", [(num + b" (RFC822 {%d}" % len(raw), raw), b")"])

    def logout(self):
        self.logged_out = True
        return ("BYE", [b""])


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/tools.db")


# ── Parsing puro ──────────────────────────────────────────────
def test_parse_message_extrai_campos_e_snippet():
    raw = _raw("Alice <alice@x.com>", "Reunião amanhã",
               "Oi, podemos falar amanhã às 10h?\n\nAbraço")
    d = em.parse_message(raw)
    assert d["from"] == "Alice <alice@x.com>"
    assert d["subject"] == "Reunião amanhã"
    assert "podemos falar amanhã" in d["snippet"]
    assert d["date"].startswith("2026-07-06")


def test_parse_message_assunto_mime_codificado():
    # "Olá" em MIME encoded-word (UTF-8 base64)
    raw = _raw("b@x.com", "=?utf-8?b?T2zDoQ==?=", "corpo")
    assert em.parse_message(raw)["subject"] == "Olá"


def test_since_janelas():
    now = datetime(2026, 7, 6, 15, 0)
    assert em._since("hoje", now) == datetime(2026, 7, 6)
    assert em._since("ontem", now) == datetime(2026, 7, 5)
    assert em._since("esta semana", now) == datetime(2026, 6, 29)
    assert em._since("7d", now) == datetime(2026, 6, 29)
    assert em._since("", now) == datetime(2026, 7, 6)


# ── fetch_recent com fake (read-only + ordem) ─────────────────
def test_fetch_recent_readonly_e_mais_novos_primeiro():
    msgs = {b"1": _raw("a@x.com", "Primeiro", "um"),
            b"2": _raw("b@x.com", "Segundo", "dois")}
    fake = _FakeIMAP(msgs)
    out = em.fetch_recent(datetime(2026, 7, 1), limit=10, connect=lambda: fake)
    assert fake.select_readonly is True          # EXAMINE = nunca marca/apaga
    assert fake.logged_out is True
    assert [m["subject"] for m in out] == ["Segundo", "Primeiro"]   # reverso


def test_fetch_recent_respeita_limit():
    msgs = {str(i).encode(): _raw("a@x.com", f"S{i}", "x") for i in range(1, 6)}
    fake = _FakeIMAP(msgs)
    out = em.fetch_recent(datetime(2026, 7, 1), limit=2, connect=lambda: fake)
    assert len(out) == 2


# ── Via run_tool: porteira + credenciais ──────────────────────
def test_email_negado_sem_grant(db):
    r = run_tool("email.recent", {"since": "hoje"}, db)
    assert r["ok"] is False and r.get("denied") is True and r["scope"] == "email.read"


def test_email_com_grant_mas_sem_credenciais(db, monkeypatch):
    for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS"):
        monkeypatch.delenv(k, raising=False)
    db.grant_permission("email.read")
    r = run_tool("email.recent", {"since": "hoje"}, db)
    assert r["ok"] is False and "não configurado" in r["error"]


def test_email_happy_path_via_run_tool(db, monkeypatch):
    fake = _FakeIMAP({b"1": _raw("chefe@x.com", "Relatório", "Segue em anexo o Q3.")})
    monkeypatch.setattr(em, "_connect", lambda: fake)
    db.grant_permission("email.read")
    r = run_tool("email.recent", {"since": "hoje", "limit": 5}, db)
    assert r["ok"] is True
    assert r["result"]["count"] == 1
    assert r["result"]["emails"][0]["subject"] == "Relatório"
    assert fake.select_readonly is True          # confirma leitura sem efeitos
