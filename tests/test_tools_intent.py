"""Ponte linguagem-natural → ferramenta (M6, Épico 6.3, DoD).

Fecha o M6: as frases-alvo do DoD ('resuma meus e-mails de hoje', 'o que tenho
na agenda amanhã') chegam à ferramenta certa, passam pela porteira e voltam
formatadas. Determinístico — sem LLM.
"""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import src.tools.email_read as em
from app import app
from src import runtime as rt
from src.storage import DatabaseManager
from src.tools.intent import detect_intent, format_answer


# ── Detecção de intenção ──────────────────────────────────────
def test_detecta_email():
    assert detect_intent("resuma meus e-mails de hoje") == \
        ("email.recent", {"since": "resuma meus e-mails de hoje"})
    assert detect_intent("tem algo novo na caixa de entrada?")[0] == "email.recent"


def test_detecta_agenda():
    name, args = detect_intent("o que tenho na agenda amanhã")
    assert name == "calendar.events" and "amanhã" in args["when"]
    assert detect_intent("quais meus compromissos essa semana")[0] == "calendar.events"


def test_detecta_arquivos():
    assert detect_intent("lê o arquivo C:/notas/todo.md") == \
        ("files.read", {"path": "C:/notas/todo.md"})
    assert detect_intent("busca arquivos sobre imposto")[0] == "files.search"


def test_nao_entende_conversa_normal():
    assert detect_intent("qual a capital da França?") is None
    assert detect_intent("") is None


# ── Formatação ────────────────────────────────────────────────
def test_formata_agenda_e_email():
    cal = format_answer("calendar.events", {"count": 1, "when": "amanhã",
        "events": [{"summary": "Dentista", "start": "2026-07-07T14:00",
                    "location": "Clínica", "all_day": False}]})
    assert "Dentista" in cal and "14:00" in cal and "Clínica" in cal
    vazio = format_answer("calendar.events", {"count": 0, "when": "amanhã"})
    assert "Nada na agenda" in vazio


# ── Endpoint /api/agency/ask (porteira ponta-a-ponta) ─────────
@pytest.fixture
def client(tmp_path):
    prev = rt.db
    rt.db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/ask.db")
    yield TestClient(app)
    rt.db = prev


def test_ask_email_negado_sem_permissao(client):
    r = client.post("/api/agency/ask", json={"text": "resuma meus e-mails de hoje"})
    d = r.json()
    assert d["ok"] is False and d["denied"] is True and d["tool"] == "email.recent"
    assert "Permiss" in d["answer"]


def test_ask_nao_entende(client):
    d = client.post("/api/agency/ask", json={"text": "me conte uma piada"}).json()
    assert d["ok"] is False and d["understood"] is False


def test_ask_agenda_ok_com_permissao(client, tmp_path):
    amanha = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    ics = tmp_path / "ag.ics"
    ics.write_text("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Médico\n"
                   f"DTSTART:{amanha}T100000\nEND:VEVENT\nEND:VCALENDAR\n",
                   encoding="utf-8")
    rt.db.grant_permission("calendar.read", note=str(ics))
    d = client.post("/api/agency/ask",
                    json={"text": "o que tenho na agenda amanhã"}).json()
    assert d["ok"] is True and d["tool"] == "calendar.events"
    assert "Médico" in d["answer"]


def test_ask_email_ok_com_permissao(client, monkeypatch):
    from email.message import EmailMessage

    def _raw(frm, subj):
        m = EmailMessage(); m["From"] = frm; m["Subject"] = subj
        m["Date"] = "Mon, 06 Jul 2026 09:00:00 +0000"; m.set_content("oi")
        return m.as_bytes()

    class _Fake:
        def select(self, mb, readonly=False): self.ro = readonly; return ("OK", [b"1"])
        def search(self, cs, *c): return ("OK", [b"1"])
        def fetch(self, n, s): return ("OK", [(b"1 (RFC822 {10}", _raw("chefe@x.com", "Q3")), b")"])
        def logout(self): return ("BYE", [b""])

    monkeypatch.setattr(em, "_connect", lambda: _Fake())
    rt.db.grant_permission("email.read")
    d = client.post("/api/agency/ask",
                    json={"text": "resuma meus e-mails de hoje"}).json()
    assert d["ok"] is True and d["tool"] == "email.recent"
    assert "Q3" in d["answer"] and "chefe@x.com" in d["answer"]
