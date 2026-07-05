"""Routers de voz e backup (10º e 11º grupos extraídos na M1).
Voz é stateless (módulos opcionais → fallback do navegador). Backup lê db/
knowledge_db via runtime; o import limpa o cache de sessões compartilhado.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.voice import router as voice_router
from routers.backup import router as backup_router


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── Voz ───────────────────────────────────────────────────────────
def test_voz_rotas_registradas():
    paths = {r.path for r in voice_router.routes}
    assert {"/api/stt", "/api/tts"} <= paths


def test_tts_texto_vazio_400():
    # Se edge-tts não estiver instalado retorna 503 (também um caminho válido);
    # com ele instalado, texto vazio → 400. Aceita ambos os "não-200".
    r = _client(voice_router).get("/api/tts?text=")
    assert r.status_code in (400, 503)


# ── Backup ────────────────────────────────────────────────────────
def test_backup_rotas_registradas():
    paths = {r.path for r in backup_router.routes}
    assert {"/api/export/obsidian", "/api/export", "/api/import"} <= paths


def test_import_json_invalido():
    rt.configure(db=None, knowledge_db=None)
    r = _client(backup_router).request("POST", "/api/import", content=b"nao-e-json{{")
    assert r.json()["ok"] is False


def test_import_limpa_sessoes_compartilhadas():
    shared = {"s1": ["msg"], "s2": ["x"]}

    class FakeDB:
        def import_all(self, data):
            return {"sessions": 2}

    rt.configure(db=FakeDB(), knowledge_db=None, sessions=shared)
    r = _client(backup_router).post("/api/import", json={"sessions": []})
    assert r.json()["ok"] is True
    assert shared == {}   # cache em memória de sessões foi limpo


def test_export_all_agrega_conhecimento():
    class FakeDB:
        def export_all(self):
            return {"counts": {}, "sessions": []}

    class FakeKB:
        def all_rows(self, n):
            return [{"url": "u", "title": "t"}]

    rt.configure(db=FakeDB(), knowledge_db=FakeKB())
    r = _client(backup_router).get("/api/export")
    body = r.json()
    assert body["counts"]["knowledge"] == 1
    assert body["knowledge"][0]["url"] == "u"
