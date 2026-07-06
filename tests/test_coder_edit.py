"""Testes da edição cirúrgica (edit_file) e do parser da ação EDITAR."""

import json

import pytest

from src.coder import CoderWorkspace
from routers.coder import parse_coder_action as _parse_coder_action


@pytest.fixture
def ws(tmp_path):
    return CoderWorkspace(str(tmp_path))


# ── edit_file ────────────────────────────────────────────────────
def test_edit_troca_trecho_unico(ws):
    ws.write_file("m.py", "def f():\n    return 1\n\ndef g():\n    return 2\n")
    out = ws.edit_file("m.py", "    return 1", "    return 42")
    assert out.startswith("OK")
    c = ws.current_content("m.py")
    assert "return 42" in c and "return 2" in c   # só o alvo mudou


def test_edit_trecho_inexistente_falha_sem_tocar(ws):
    ws.write_file("m.py", "a = 1\n")
    out = ws.edit_file("m.py", "b = 2", "b = 3")
    assert "não encontrado" in out
    assert ws.current_content("m.py") == "a = 1\n"   # intacto


def test_edit_trecho_ambiguo_falha(ws):
    ws.write_file("m.py", "x = 0\nx = 0\n")
    out = ws.edit_file("m.py", "x = 0", "x = 9")
    assert "2x" in out or "aparece" in out
    assert ws.current_content("m.py") == "x = 0\nx = 0\n"   # nada mudou


def test_edit_arquivo_inexistente(ws):
    out = ws.edit_file("nao_existe.py", "a", "b")
    assert "não encontrado" in out


def test_edit_eh_reversivel(ws):
    ws.write_file("m.py", "valor = 1\n")
    ws.edit_file("m.py", "valor = 1", "valor = 2")
    assert "valor = 2" in ws.current_content("m.py")
    ws.undo_last()
    assert ws.current_content("m.py") == "valor = 1\n"


# ── parser EDITAR ────────────────────────────────────────────────
def test_parse_editar_marcadores():
    content = (
        "EDITAR src/m.py\n"
        "<<<<<<< BUSCAR\n"
        "def soma(a, b):\n    return a - b\n"
        "=======\n"
        "def soma(a, b):\n    return a + b\n"
        ">>>>>>> FIM\n"
    )
    action, arg, payload = _parse_coder_action(content)
    assert action == "edit"
    assert arg == "src/m.py"
    spec = json.loads(payload)
    assert "return a - b" in spec["old"]
    assert "return a + b" in spec["new"]


def test_parse_editar_com_fence_antes_dos_marcadores():
    # Modelos às vezes embrulham em ```; o parser deve achar os marcadores mesmo assim.
    content = (
        "EDITAR app.py\n```\n"
        "<<<<<<<\nold line\n=======\nnew line\n>>>>>>>\n```\n"
    )
    action, arg, payload = _parse_coder_action(content)
    assert action == "edit" and arg == "app.py"
    assert json.loads(payload)["new"] == "new line"


def test_parse_editar_end_to_end(ws):
    ws.write_file("calc.py", "def soma(a, b):\n    return a - b\n")
    content = (
        "EDITAR calc.py\n<<<<<<<\n    return a - b\n=======\n    return a + b\n>>>>>>>\n"
    )
    action, arg, payload = _parse_coder_action(content)
    spec = json.loads(payload)
    out = ws.edit_file(arg, spec["old"], spec["new"])
    assert out.startswith("OK")
    assert "return a + b" in ws.current_content("calc.py")
