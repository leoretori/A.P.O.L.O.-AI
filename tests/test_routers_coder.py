"""Endpoint do A.P.O.L.O. Coder (routers/coder.py) — o último e maior endpoint
extraído do monólito na M1. O parser (parse_coder_action) já é coberto à exaustão
em test_coder_autonomy/test_coder/test_coder_edit; aqui garantimos que a rota foi
registrada e que o parser está acessível pelo novo módulo.
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.coder import CoderWorkspace
import routers.coder as coder_mod
from routers.coder import router, parse_coder_action


def test_rota_registrada():
    assert any(getattr(r, "path", None) == "/api/coder" for r in router.routes)


def test_parser_acessivel_pelo_router():
    # sanity: o parser mora agora em routers.coder e responde às ações básicas
    assert parse_coder_action("LISTAR .")[0] == "list"
    assert parse_coder_action("BUSCAR_WEB: fastapi sse")[0] == "web"
    assert parse_coder_action("CONSULTAR asyncio")[0] == "consult"
    assert parse_coder_action("resposta final sem acao")[0] == "done"


def test_workspace_vazio_barra_antes_de_chamar_o_modelo(tmp_path, monkeypatch):
    """Achado ao vivo (2026-07-14): reaproveitar uma tarefa antiga com 'Executar'
    depois de reiniciar o app (ponteiro da cópia sandbox zera no restart) rodava
    o loop inteiro contra um workspace vazio — minutos de geração fracassada até
    'concluir' sem ter feito nada. Agora barra ANTES de qualquer chamada ao LLM."""
    def _boom(*a, **k):
        raise AssertionError("não deveria chamar o modelo com workspace vazio")
    monkeypatch.setattr(coder_mod, "chat_resilient", _boom)

    ws = CoderWorkspace(root=str(tmp_path / "vazio"))
    rt.configure(coder_ws=ws, model="qwen-7b", get_chat_model=lambda: "qwen-1.5b",
                 project_mem=None, lesson_mem=None, gpu_gate=None, db=None)

    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/api/coder", json={"message": "melhore o código", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(ln[6:]) for ln in r.text.splitlines() if ln.startswith("data: ")]
    assert eventos[0]["type"] == "error"
    assert "vazio" in eventos[0]["message"].lower()
    assert len(eventos) == 1   # nada mais rodou depois do erro
