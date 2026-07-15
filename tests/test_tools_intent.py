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


def test_detecta_relogio():
    # DoD do M5: "Apolo, que horas são?" → ferramenta clock (sem permissão).
    assert detect_intent("que horas são?") == ("clock", {})
    assert detect_intent("que dia é hoje") == ("clock", {})


def test_detecta_visao_da_tela():
    # M22.2: o agente vê a tela sozinho quando você pergunta sobre ela.
    assert detect_intent("veja minha tela") == ("vision.screen", {})
    assert detect_intent("o que tem na tela agora?")[0] == "vision.screen"
    assert detect_intent("tira uma screenshot")[0] == "vision.screen"
    assert detect_intent("o que você vê?")[0] == "vision.screen"


def test_detecta_visao_da_camera():
    # M22.3: câmera é escopo/intenção DIFERENTE da tela.
    assert detect_intent("tira uma foto pela câmera") == ("vision.camera", {})
    assert detect_intent("veja pela webcam")[0] == "vision.camera"
    assert detect_intent("me veja")[0] == "vision.camera"


def test_frase_com_tela_e_foto_prioriza_tela():
    # "tira uma foto DA MINHA TELA" é ambíguo de propósito — o usuário quer um
    # screenshot (usou "foto" coloquialmente); a tela ganha por ser o caso mais
    # comum e o menos sensível dos dois escopos.
    assert detect_intent("tira uma foto da minha tela")[0] == "vision.screen"


def test_nao_entende_conversa_normal():
    assert detect_intent("qual a capital da França?") is None
    assert detect_intent("") is None


def test_ask_relogio_sem_permissao_funciona(client):
    # clock tem scope "" → responde sem grant (bom p/ o DoD do wake word).
    d = client.post("/api/agency/ask", json={"text": "que horas são?"}).json()
    assert d["ok"] is True and d["tool"] == "clock"
    assert "são" in d["answer"] or ":" in d["answer"]


# ── Formatação ────────────────────────────────────────────────
def test_formata_agenda_e_email():
    cal = format_answer("calendar.events", {"count": 1, "when": "amanhã",
        "events": [{"summary": "Dentista", "start": "2026-07-07T14:00",
                    "location": "Clínica", "all_day": False}]})
    assert "Dentista" in cal and "14:00" in cal and "Clínica" in cal
    vazio = format_answer("calendar.events", {"count": 0, "when": "amanhã"})
    assert "Nada na agenda" in vazio


def test_formata_visao_da_tela():
    ok = format_answer("vision.screen", {"ok": True, "described": True,
                                         "description": "um editor de código"})
    assert ok == "um editor de código"
    sem_modelo = format_answer("vision.screen",
        {"ok": True, "described": False, "describe_error": "sem modelo de visão"})
    assert "Capturei a tela" in sem_modelo and "sem modelo de visão" in sem_modelo
    falhou = format_answer("vision.screen", {"ok": False, "error": "sem display"})
    assert "Não consegui ver a tela" in falhou and "sem display" in falhou


def test_formata_visao_da_camera():
    ok = format_answer("vision.camera", {"ok": True, "described": True,
                                         "description": "um cachorro no sofá"})
    assert ok == "um cachorro no sofá"
    sem_modelo = format_answer("vision.camera",
        {"ok": True, "described": False, "describe_error": "sem modelo de visão"})
    assert "Tirei a foto" in sem_modelo and "sem modelo de visão" in sem_modelo
    falhou = format_answer("vision.camera", {"ok": False, "error": "opencv-python ausente"})
    assert "Não consegui usar a câmera" in falhou and "opencv-python" in falhou


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


def test_ask_visao_negado_sem_permissao(client):
    r = client.post("/api/agency/ask", json={"text": "veja minha tela"})
    d = r.json()
    assert d["ok"] is False and d["denied"] is True and d["tool"] == "vision.screen"


def test_ask_visao_ok_com_permissao(client, monkeypatch):
    rt.db.grant_permission("vision.screen")
    monkeypatch.setattr("src.vision_read.capture_screen",
                        lambda: {"ok": True, "size": [1, 1], "image_b64": "x"})
    monkeypatch.setattr("src.tools.vision._describe",
                        lambda image_b64, prompt: {"ok": True, "description": "uma planilha aberta"})
    d = client.post("/api/agency/ask", json={"text": "o que tem na minha tela?"}).json()
    assert d["ok"] is True and d["tool"] == "vision.screen"
    assert d["answer"] == "uma planilha aberta"


def test_ask_camera_negado_sem_permissao(client):
    r = client.post("/api/agency/ask", json={"text": "tira uma foto pela câmera"})
    d = r.json()
    assert d["ok"] is False and d["denied"] is True and d["tool"] == "vision.camera"


def test_ask_camera_ok_com_permissao(client, monkeypatch):
    rt.db.grant_permission("vision.camera")
    monkeypatch.setattr("src.vision_read.capture_camera",
                        lambda: {"ok": True, "size": [1, 1], "image_b64": "x"})
    monkeypatch.setattr("src.tools.vision._describe",
                        lambda image_b64, prompt: {"ok": True, "description": "uma sala vazia"})
    d = client.post("/api/agency/ask", json={"text": "veja pela webcam"}).json()
    assert d["ok"] is True and d["tool"] == "vision.camera"
    assert d["answer"] == "uma sala vazia"


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
