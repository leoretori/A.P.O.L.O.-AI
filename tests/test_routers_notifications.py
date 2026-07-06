"""Router de notificações + lembretes (routers/notifications.py).
Cobre os endpoints de lembretes (M4 4.2) com um db falso."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.notifications import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/notifications", "/api/notifications/read",
            "/api/reminders", "/api/reminders/{reminder_id}/done"} <= paths


def test_lista_lembretes():
    class FakeDB:
        def list_reminders(self, pending, limit):
            return [{"id": 1, "text": "revisar o PR", "due_at": None, "done": False}]
    rt.configure(db=FakeDB())
    r = _client().get("/api/reminders?pending=true")
    assert r.status_code == 200
    assert r.json()["reminders"][0]["text"] == "revisar o PR"


def test_cria_lembrete_manual():
    saved = {}
    class FakeDB:
        def save_reminder(self, text, due, session_id):
            saved["text"] = text; saved["due"] = due
            return 7
    rt.configure(db=FakeDB())
    r = _client().post("/api/reminders", json={"text": "ligar amanhã",
                                               "due_at": "2026-07-07T09:00:00"})
    assert r.status_code == 200 and r.json() == {"ok": True, "id": 7}
    assert saved["text"] == "ligar amanhã" and saved["due"].hour == 9


def test_cria_lembrete_texto_vazio():
    rt.configure(db=None)
    r = _client().post("/api/reminders", json={"text": "  "})
    assert r.json()["ok"] is False


def test_conclui_lembrete():
    class FakeDB:
        def mark_reminder_done(self, rid): return rid == 3
    rt.configure(db=FakeDB())
    assert _client().post("/api/reminders/3/done").json() == {"ok": True}
    assert _client().post("/api/reminders/9/done").json() == {"ok": False}
