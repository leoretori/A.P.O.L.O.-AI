"""Ferramentas de leitura do Coder (routers/coder_tools.py) — 14º grupo na M1.
Cobre files, lessons, tasks, read, git — lendo coder_ws/lesson_mem/db do runtime.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.coder_tools import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeWS:
    root = "/ws"

    def tree(self, n): return "arvore"

    def list_files(self, n): return ["a.py"]

    def list_changes(self): return []

    def read_file(self, path, n): return f"conteudo de {path}"

    def git_status(self): return {"branch": "main", "dirty": False}

    def git_diff(self, path): return f"diff {path}"


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/coder/files", "/api/coder/lessons", "/api/coder/lessons/{lesson_id}",
        "/api/coder/tasks", "/api/coder/read", "/api/coder/git", "/api/coder/git/diff",
    } <= paths


def test_files():
    rt.configure(coder_ws=FakeWS())
    r = _client().get("/api/coder/files")
    body = r.json()
    assert body["root"] == "/ws" and body["files"] == ["a.py"]


def test_lessons_sem_memoria():
    rt.configure(lesson_mem=None)
    r = _client().get("/api/coder/lessons")
    assert r.json() == {"count": 0, "lessons": []}


def test_lessons_com_memoria():
    class FakeLM:
        def count(self): return 2
        def recent(self, n): return [{"lesson": "não reescreva módulos"}]
    rt.configure(lesson_mem=FakeLM())
    r = _client().get("/api/coder/lessons")
    assert r.json()["count"] == 2


def test_lesson_delete():
    apagados = []

    class FakeLM:
        def delete(self, lid):
            apagados.append(lid)
            return True
    rt.configure(lesson_mem=FakeLM())
    r = _client().delete("/api/coder/lessons/7")
    assert r.json()["ok"] is True and apagados == [7]


def test_read_arquivo():
    rt.configure(coder_ws=FakeWS())
    r = _client().get("/api/coder/read?path=app.py")
    assert r.json()["content"] == "conteudo de app.py"


def test_git_status_e_diff():
    rt.configure(coder_ws=FakeWS())
    c = _client()
    assert c.get("/api/coder/git").json()["branch"] == "main"
    assert "diff" in c.get("/api/coder/git/diff?path=x").json()["diff"]


def test_tasks_sem_db():
    rt.configure(db=None)
    r = _client().get("/api/coder/tasks")
    assert r.json()["stats"]["total"] == 0
