"""Routers de agendamentos e notificações (5º e 6º grupos extraídos na M1).
Ambos dependem só de `rt.db`. Cobrem validação de horário e o contrato de cada rota.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.schedules import router as schedules_router
from routers.notifications import router as notifications_router


class FakeDB:
    def __init__(self):
        self.schedules = []
        self.marked = 0
        self.cleared = 0

    # schedules
    def list_schedules(self):
        return self.schedules

    def add_schedule(self, topic, t):
        row = {"id": len(self.schedules) + 1, "topic": topic, "time_of_day": t}
        self.schedules.append(row)
        return row

    def delete_schedule(self, sid):
        return True

    def toggle_schedule(self, sid):
        return True

    # notifications
    def list_notifications(self, limit, unread_only, min_priority=0):
        return [{"message": "oi"}]

    def unread_count(self):
        return 3

    def mark_notifications_read(self):
        return 5

    def clear_notifications(self):
        return 7


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── Schedules ─────────────────────────────────────────────────────
def test_add_schedule_valido():
    rt.configure(db=FakeDB())
    r = _client(schedules_router).post("/api/schedules", json={"topic": "redis streams", "time_of_day": "07:30"})
    assert r.json()["ok"] is True
    assert r.json()["schedule"]["topic"] == "redis streams"


def test_add_schedule_horario_invalido():
    rt.configure(db=FakeDB())
    r = _client(schedules_router).post("/api/schedules", json={"topic": "kafka", "time_of_day": "25:99"})
    assert r.json()["ok"] is False
    assert "horário" in r.json()["error"]


def test_add_schedule_topico_curto():
    rt.configure(db=FakeDB())
    r = _client(schedules_router).post("/api/schedules", json={"topic": "x"})
    assert r.json()["ok"] is False


def test_toggle_e_delete_schedule():
    rt.configure(db=FakeDB())
    c = _client(schedules_router)
    assert c.post("/api/schedules/1/toggle").json()["ok"] is True
    assert c.delete("/api/schedules/1").json()["ok"] is True


# ── Notifications ─────────────────────────────────────────────────
def test_list_notifications_com_contador():
    rt.configure(db=FakeDB())
    r = _client(notifications_router).get("/api/notifications")
    body = r.json()
    assert body["unread"] == 3 and body["items"][0]["message"] == "oi"


def test_read_e_clear_notifications():
    rt.configure(db=FakeDB())
    c = _client(notifications_router)
    assert c.post("/api/notifications/read").json()["marked"] == 5
    assert c.delete("/api/notifications").json()["cleared"] == 7
