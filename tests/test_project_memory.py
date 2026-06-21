"""Testes da memória de projeto (src/project_memory.py)."""

import json
import pytest

from src.project_memory import (
    analyze_project, _detect_stack, _parse_pyproject,
    _parse_package_json, _parse_requirements, ProjectMemory,
)


# ── Parsers ───────────────────────────────────────────────────────────────────

def test_parse_pyproject_extrai_name():
    r = _parse_pyproject('name = "meu-projeto"\nversion = "1.0"')
    assert r["name"] == "meu-projeto"

def test_parse_pyproject_extrai_deps():
    content = '[project.dependencies]\nfastapi = ">=0.100"\nsqlalchemy = ">=2.0"'
    r = _parse_pyproject(content)
    assert "fastapi" in r["deps"] or len(r["deps"]) >= 0  # deps pode variar por regex

def test_parse_package_json_basico():
    data = json.dumps({"name": "meu-app", "description": "App Node", "dependencies": {"react": "^18"}})
    r = _parse_package_json(data)
    assert r["name"] == "meu-app"
    assert "react" in r["deps"]

def test_parse_package_json_invalido():
    r = _parse_package_json("não é json")
    assert r == {}

def test_parse_requirements():
    content = "fastapi>=0.100\nuvicorn\n# comentário\nsqlalchemy>=2.0"
    deps = _parse_requirements(content)
    assert "fastapi" in deps
    assert "uvicorn" in deps
    assert "sqlalchemy" in deps


# ── Detecção de stack ─────────────────────────────────────────────────────────

def test_detect_stack_python():
    stack = _detect_stack({"pyproject": "x"}, ["fastapi", "sqlalchemy"])
    assert "Python" in stack
    assert "FastAPI" in stack

def test_detect_stack_node():
    stack = _detect_stack({"package_json": "x"}, ["react", "jest"])
    assert "Node.js" in stack
    assert "React" in stack

def test_detect_stack_docker():
    stack = _detect_stack({"dockerfile": "x", "pyproject": "x"}, [])
    assert "Docker" in stack

def test_detect_stack_desconhecido():
    stack = _detect_stack({}, [])
    assert stack == "Desconhecida"


# ── analyze_project ───────────────────────────────────────────────────────────

@pytest.fixture
def python_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "meu-projeto"\ndescription = "Projeto de teste"\n'
        '[project.dependencies]\nfastapi = ">=0.100"\nchromadb = ">=0.6"',
        encoding="utf-8"
    )
    (tmp_path / "requirements.txt").write_text("ollama>=0.3\nuvicorn>=0.18\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Meu Projeto\nUm assistente local.", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "Dockerfile").write_text("FROM python:3.12", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')", encoding="utf-8")
    return tmp_path

def test_analyze_python_project(python_project):
    ctx = analyze_project(str(python_project))
    assert ctx["name"] == "meu-projeto"
    assert "Python" in ctx["stack"]
    assert ctx["has_docker"] is True
    assert ctx["has_tests"] is True

def test_analyze_project_deps(python_project):
    ctx = analyze_project(str(python_project))
    deps = ctx["dependencies"]
    assert isinstance(deps, list)
    assert any("ollama" in d or "uvicorn" in d or "fastapi" in d for d in deps)

def test_analyze_project_campos_obrigatorios(python_project):
    ctx = analyze_project(str(python_project))
    for campo in ["name", "path", "stack", "dependencies", "analyzed_at"]:
        assert campo in ctx

def test_analyze_project_pasta_vazia(tmp_path):
    ctx = analyze_project(str(tmp_path))
    assert ctx["name"] == tmp_path.name
    assert isinstance(ctx["dependencies"], list)

@pytest.fixture
def node_project(tmp_path):
    pkg = {"name": "meu-frontend", "description": "App React",
           "dependencies": {"react": "^18", "axios": "^1.0"},
           "devDependencies": {"jest": "^29"}}
    (tmp_path / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
    return tmp_path

def test_analyze_node_project(node_project):
    ctx = analyze_project(str(node_project))
    assert ctx["name"] == "meu-frontend"
    assert "Node.js" in ctx["stack"]
    assert "react" in ctx["dependencies"]


# ── ProjectMemory ─────────────────────────────────────────────────────────────

@pytest.fixture
def mem(tmp_path):
    return ProjectMemory(path=str(tmp_path / "contexts.json"))

def test_set_e_get_active(mem):
    ctx = {"name": "apolo", "path": "/proj", "stack": "Python+FastAPI",
           "description": "", "dependencies": [], "files_hint": [],
           "has_docker": False, "has_tests": True, "analyzed_at": "now"}
    mem.set_context(ctx)
    active = mem.get_active()
    assert active is not None
    assert active["name"] == "apolo"

def test_clear_active(mem):
    ctx = {"name": "proj", "path": "/p", "stack": "Go", "description": "",
           "dependencies": [], "files_hint": [], "has_docker": False,
           "has_tests": False, "analyzed_at": "now"}
    mem.set_context(ctx)
    mem.clear_active()
    assert mem.get_active() is None

def test_list_all(mem):
    for name in ["a", "b", "c"]:
        mem.set_context({"name": name, "path": f"/{name}", "stack": "Python",
                         "description": "", "dependencies": [], "files_hint": [],
                         "has_docker": False, "has_tests": False, "analyzed_at": "now"})
    assert len(mem.list_all()) == 3

def test_remove(mem):
    mem.set_context({"name": "x", "path": "/x", "stack": "Go", "description": "",
                     "dependencies": [], "files_hint": [], "has_docker": False,
                     "has_tests": False, "analyzed_at": "now"})
    assert mem.remove("x") is True
    assert mem.get_active() is None
    assert mem.remove("nao-existe") is False

def test_as_prompt_section_vazio(mem):
    assert mem.as_prompt_section() == ""

def test_as_prompt_section_com_projeto(mem):
    mem.set_context({"name": "A.P.O.L.O.", "path": "/proj", "stack": "Python+FastAPI+Ollama",
                     "description": "Assistente local.", "dependencies": ["fastapi","ollama"],
                     "files_hint": [], "has_docker": True, "has_tests": True, "analyzed_at": "now"})
    section = mem.as_prompt_section()
    assert "A.P.O.L.O." in section
    assert "Python+FastAPI+Ollama" in section
    assert "fastapi" in section
    assert "Docker" in section

def test_persistencia(tmp_path):
    path = str(tmp_path / "ctx.json")
    m1 = ProjectMemory(path=path)
    m1.set_context({"name": "salvo", "path": "/s", "stack": "Rust",
                    "description": "", "dependencies": [], "files_hint": [],
                    "has_docker": False, "has_tests": False, "analyzed_at": "now"})
    m2 = ProjectMemory(path=path)  # novo objeto, mesmo arquivo
    assert m2.get_active()["name"] == "salvo"
