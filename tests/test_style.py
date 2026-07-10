"""Ritmo & tom (M17.2): tom de resposta derivado das preferências do perfil."""

from src.style import derive_tone, describe, style_directive


class FakeProfile:
    def __init__(self, groups=None): self._g = groups or {}
    def by_category(self): return self._g


def _prof(*prefs):
    return FakeProfile({"preference": [{"fact": p, "category": "preference"} for p in prefs]})


def test_tom_direto():
    assert derive_tone(_prof("prefiro respostas diretas e concisas")) == "direct"
    assert derive_tone(_prof("gosto de objetividade, sem rodeio")) == "direct"


def test_tom_detalhado():
    assert derive_tone(_prof("prefiro explicações detalhadas com exemplos")) == "detailed"
    assert derive_tone(_prof("gosto de respostas passo a passo e didáticas")) == "detailed"


def test_tom_equilibrado_sem_sinal():
    assert derive_tone(_prof("gosto de café")) == "balanced"
    assert derive_tone(None) == "balanced"
    assert derive_tone(FakeProfile({})) == "balanced"


def test_tom_empate_vira_equilibrado():
    # sinal direto E detalhado no mesmo peso → não impõe estilo
    assert derive_tone(_prof("respostas diretas", "mas detalhadas")) == "balanced"


def test_acento_nao_atrapalha():
    assert derive_tone(_prof("prefiro respostas concisas")) == "direct"  # com/sem acento


def test_le_tambem_valores():
    p = FakeProfile({"value": [{"fact": "valorizo objetividade e ir direto ao ponto",
                                "category": "value"}]})
    assert derive_tone(p) == "direct"


def test_style_directive():
    assert "DIRETO" in style_directive("direct")
    assert "DETALHADO" in style_directive("detailed")
    assert style_directive("balanced") == ""  # equilibrado não injeta nada


def test_describe():
    d = describe(_prof("prefiro respostas diretas"))
    assert d["tone"] == "direct" and d["label"] == "Direto" and d["adapted"] is True
    d2 = describe(_prof("gosto de café"))
    assert d2["tone"] == "balanced" and d2["adapted"] is False


def test_endpoint_style(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers.profile import router
    from src import runtime as rt
    monkeypatch.setattr(rt, "profile", _prof("prefiro respostas diretas"))
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).get("/api/style")
    assert r.status_code == 200 and r.json()["tone"] == "direct"
