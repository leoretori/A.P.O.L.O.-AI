"""Testes do sistema de testes inteligentes (find_related_tests + _parse_pytest_output)."""

import pytest
from src.coder import CoderWorkspace, _parse_pytest_output


# ── _parse_pytest_output ──────────────────────────────────────────────────────

def test_parse_passed():
    out = "tests/test_foo.py::test_bar PASSED\ntests/test_foo.py::test_baz PASSED"
    r = _parse_pytest_output(out)
    assert r["passed"] == 2
    assert r["failed"] == 0
    assert r["total"] == 2

def test_parse_failed():
    out = "tests/test_foo.py::test_bar FAILED\ntests/test_foo.py::test_ok PASSED"
    r = _parse_pytest_output(out)
    assert r["failed"] == 1
    assert r["passed"] == 1

def test_parse_skipped():
    out = "tests/test_foo.py::test_skip SKIPPED"
    r = _parse_pytest_output(out)
    assert r["skipped"] == 1
    assert r["passed"] == 0

def test_parse_empty_output():
    r = _parse_pytest_output("")
    assert r["total"] == 0
    assert r["results"] == []

def test_parse_resultado_tem_campos():
    out = "tests/test_x.py::test_algo PASSED"
    r = _parse_pytest_output(out)
    assert r["results"][0]["file"] == "tests/test_x.py"
    assert r["results"][0]["test"] == "test_algo"
    assert r["results"][0]["status"] == "passed"

def test_parse_ignora_linhas_sem_status():
    out = "PASSED  5\ncollected 5 items\ntests/test_x.py::test_ok PASSED"
    r = _parse_pytest_output(out)
    assert r["total"] == 1

def test_parse_error_conta_como_falha():
    out = "tests/test_x.py::test_broken ERROR"
    r = _parse_pytest_output(out)
    assert r["failed"] == 1


# ── find_related_tests ────────────────────────────────────────────────────────

@pytest.fixture
def ws(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_providers.py").write_text("def test_ok(): pass")
    (tmp_path / "tests" / "test_providers_extra.py").write_text("def test_x(): pass")
    (tmp_path / "tests" / "test_routing.py").write_text("def test_r(): pass")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "providers.py").write_text("class P: pass")
    (tmp_path / "src" / "routing.py").write_text("def is_complex(q): return False")
    w = CoderWorkspace(root=str(tmp_path))
    return w

def test_find_tests_por_nome_exato(ws):
    found = ws.find_related_tests("src/providers.py")
    names = [f.split("/")[-1] for f in found]
    assert "test_providers.py" in names

def test_find_tests_por_prefixo(ws):
    found = ws.find_related_tests("src/providers.py")
    names = [f.split("/")[-1] for f in found]
    assert "test_providers_extra.py" in names

def test_find_tests_nao_mistura_arquivos(ws):
    found = ws.find_related_tests("src/routing.py")
    names = [f.split("/")[-1] for f in found]
    assert "test_routing.py" in names
    assert "test_providers.py" not in names

def test_find_tests_sem_match(ws):
    found = ws.find_related_tests("src/nao_existe.py")
    assert found == []

def test_find_tests_retorna_lista(ws):
    result = ws.find_related_tests("src/providers.py")
    assert isinstance(result, list)

def test_find_tests_sem_duplicatas(ws):
    found = ws.find_related_tests("src/providers.py")
    assert len(found) == len(set(found))
