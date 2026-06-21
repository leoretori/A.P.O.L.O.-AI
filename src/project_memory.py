"""Memória de Projeto — detecta e persiste o contexto do projeto ativo.

Quando o usuário aponta o Coder para uma pasta, este módulo lê os arquivos
de configuração (pyproject.toml, package.json, Dockerfile, README etc.) e
extrai a stack, dependências e padrões. O contexto é injetado no system
prompt de todo chat — o A.P.O.L.O. "sabe" o projeto sem o usuário repetir.

Armazenamento: data/project_contexts.json (lista persistente de contextos)
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PATH = "data/project_contexts.json"

# Arquivos que descrevem o projeto (lidos em ordem de prioridade)
_CONFIG_FILES = [
    ("pyproject.toml",    "pyproject"),
    ("setup.cfg",         "setup_cfg"),
    ("requirements.txt",  "requirements"),
    ("package.json",      "package_json"),
    ("go.mod",            "go_mod"),
    ("Cargo.toml",        "cargo_toml"),
    ("pom.xml",           "pom_xml"),
    ("build.gradle",      "gradle"),
    ("Dockerfile",        "dockerfile"),
    ("docker-compose.yml","docker_compose"),
    ("docker-compose.yaml","docker_compose"),
    (".env.example",      "env_example"),
    ("Makefile",          "makefile"),
    ("README.md",         "readme"),
    ("README.rst",        "readme"),
]

_MAX_FILE_CHARS = 2000  # limite por arquivo para não inflar o contexto


# ── Parsers ───────────────────────────────────────────────────────────────────

def _read_file(path: str, name: str) -> str | None:
    fp = os.path.join(path, name)
    if not os.path.isfile(fp):
        return None
    try:
        return Path(fp).read_text(encoding="utf-8", errors="ignore")[:_MAX_FILE_CHARS]
    except Exception:
        return None


def _parse_pyproject(content: str) -> dict:
    name = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
    desc = re.search(r'description\s*=\s*["\']([^"\']{5,200})["\']', content)
    python = re.search(r'python\s*=\s*["\']([^"\']+)["\']', content)
    deps_block = re.search(r'\[project\.?dependencies\](.+?)(\[|\Z)', content, re.DOTALL)
    deps = re.findall(r'["\']([a-zA-Z0-9_-]+)\s*[><=!]', deps_block.group(1) if deps_block else content)
    return {
        "name": name.group(1) if name else None,
        "description": desc.group(1) if desc else None,
        "python": python.group(1) if python else None,
        "deps": sorted(set(deps[:20])),
    }


def _parse_package_json(content: str) -> dict:
    try:
        data = json.loads(content)
        deps = list((data.get("dependencies") or {}).keys()) + \
               list((data.get("devDependencies") or {}).keys())
        return {
            "name": data.get("name"),
            "description": data.get("description"),
            "version": data.get("version"),
            "deps": sorted(set(deps[:20])),
        }
    except Exception:
        return {}


def _parse_requirements(content: str) -> list[str]:
    lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
    return [re.split(r"[><=!;]", l)[0].strip() for l in lines[:30] if re.split(r"[><=!;]", l)[0].strip()]


def _parse_go_mod(content: str) -> dict:
    module = re.search(r"^module\s+(\S+)", content, re.MULTILINE)
    go_ver = re.search(r"^go\s+(\S+)", content, re.MULTILINE)
    return {
        "module": module.group(1) if module else None,
        "go": go_ver.group(1) if go_ver else None,
    }


# ── Detecção de stack ─────────────────────────────────────────────────────────

def _detect_stack(files: dict, deps: list[str]) -> str:
    """Infere a stack tecnológica a partir dos arquivos e dependências."""
    hints: list[str] = []
    deps_lower = {d.lower() for d in deps}

    # Linguagem
    if "pyproject" in files or "requirements" in files:
        hints.append("Python")
    if "package_json" in files:
        hints.append("Node.js")
    if "go_mod" in files:
        hints.append("Go")
    if "cargo_toml" in files:
        hints.append("Rust")
    if "pom_xml" in files or "gradle" in files:
        hints.append("Java/Kotlin")

    # Frameworks
    fw_map = {
        "fastapi": "FastAPI", "django": "Django", "flask": "Flask",
        "starlette": "Starlette", "nestjs": "NestJS", "express": "Express",
        "react": "React", "vue": "Vue", "angular": "Angular", "svelte": "Svelte",
        "nextjs": "Next.js", "nuxt": "Nuxt",
        "sqlalchemy": "SQLAlchemy", "prisma": "Prisma",
        "chromadb": "ChromaDB", "langchain": "LangChain",
        "ollama": "Ollama", "openai": "OpenAI API",
        "pytorch": "PyTorch", "tensorflow": "TensorFlow",
        "pytest": "pytest", "jest": "Jest",
        "docker": "Docker",
    }
    for dep, label in fw_map.items():
        if dep in deps_lower:
            hints.append(label)

    # Infra
    if "dockerfile" in files:
        hints.append("Docker")
    if "docker_compose" in files:
        hints.append("Docker Compose")
    if "makefile" in files:
        hints.append("Makefile")

    return " + ".join(hints[:8]) if hints else "Desconhecida"


# ── Análise de projeto ────────────────────────────────────────────────────────

def analyze_project(path: str) -> dict:
    """Lê arquivos de configuração e extrai o contexto do projeto.

    Sem LLM — parsing direto, rápido e determinístico.
    """
    path = os.path.abspath(path)
    project_name = os.path.basename(path)

    # Lê os arquivos disponíveis
    files: dict[str, str] = {}
    for filename, key in _CONFIG_FILES:
        content = _read_file(path, filename)
        if content:
            files[key] = content

    # Extrai informações
    deps: list[str] = []
    description = ""
    name = project_name

    if "pyproject" in files:
        parsed = _parse_pyproject(files["pyproject"])
        name = parsed.get("name") or name
        description = parsed.get("description") or description
        deps.extend(parsed.get("deps") or [])

    if "requirements" in files:
        deps.extend(_parse_requirements(files["requirements"]))

    if "package_json" in files:
        parsed = _parse_package_json(files["package_json"])
        name = parsed.get("name") or name
        description = parsed.get("description") or description
        deps.extend(parsed.get("deps") or [])

    if "go_mod" in files:
        parsed = _parse_go_mod(files["go_mod"])
        if parsed.get("module"):
            name = parsed["module"].split("/")[-1] or name

    # Deduplica e ordena as dependências
    deps = sorted(set(d for d in deps if len(d) > 1))[:25]

    # Extrai trecho do README como descrição se não tiver
    if not description and "readme" in files:
        readme = files["readme"]
        # Pega o primeiro parágrafo não-título e não-vazio
        for line in readme.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
                description = stripped[:200]
                break

    # Detecta arquivos fonte principais (para contexto de estrutura)
    try:
        src_files = []
        for ext in [".py", ".ts", ".go", ".rs", ".java"]:
            found = list(Path(path).rglob(f"*{ext}"))
            src_files.extend([str(f.relative_to(path)).replace("\\", "/") for f in found[:10]])
        src_sample = src_files[:15]
    except Exception:
        src_sample = []

    stack = _detect_stack(files, deps)

    return {
        "name": name,
        "path": path,
        "stack": stack,
        "description": description[:200] if description else "",
        "dependencies": deps,
        "files_hint": src_sample,
        "has_docker": "dockerfile" in files or "docker_compose" in files,
        "has_tests": any(Path(path, d).is_dir() for d in ["tests", "test", "__tests__", "spec"]),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Persistência ──────────────────────────────────────────────────────────────

class ProjectMemory:
    """Armazena e recupera contextos de projeto."""

    def __init__(self, path: str = _DEFAULT_PATH):
        self._path = Path(path)
        self._data: dict = {"active": None, "contexts": {}}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"project_memory load: {e}")

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"project_memory save: {e}")

    def set_context(self, ctx: dict) -> None:
        """Salva ou atualiza o contexto de um projeto e o torna ativo."""
        name = ctx["name"]
        self._data["contexts"][name] = ctx
        self._data["active"] = name
        self._save()
        logger.info(f"[project] contexto ativo: {name} ({ctx['stack']})")

    def get_active(self) -> dict | None:
        name = self._data.get("active")
        if not name:
            return None
        return self._data["contexts"].get(name)

    def list_all(self) -> list[dict]:
        return list(self._data["contexts"].values())

    def clear_active(self) -> None:
        self._data["active"] = None
        self._save()

    def remove(self, name: str) -> bool:
        if name in self._data["contexts"]:
            del self._data["contexts"][name]
            if self._data.get("active") == name:
                self._data["active"] = None
            self._save()
            return True
        return False

    def as_prompt_section(self) -> str:
        """Formata o contexto ativo para injeção no system prompt."""
        ctx = self.get_active()
        if not ctx:
            return ""
        lines = [
            f"\n\n== Projeto ativo: {ctx['name']} ==",
            f"Caminho: {ctx['path']}",
        ]
        if ctx.get("stack"):
            lines.append(f"Stack: {ctx['stack']}")
        if ctx.get("description"):
            lines.append(f"Descrição: {ctx['description']}")
        if ctx.get("dependencies"):
            lines.append(f"Dependências principais: {', '.join(ctx['dependencies'][:12])}")
        if ctx.get("has_tests"):
            lines.append("Tem suíte de testes.")
        if ctx.get("has_docker"):
            lines.append("Tem configuração Docker.")
        lines.append(
            "Use este contexto para personalizar respostas sobre código, "
            "bibliotecas e arquitetura — sem o usuário precisar repetir o ambiente."
        )
        return "\n".join(lines)
