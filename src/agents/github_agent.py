"""Agente GitHub — lê repositórios trending e READMEs para aprender padrões reais."""

import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

# Categorias de repositórios para monitorar
GITHUB_TRENDING_URLS = [
    ("Python — Trending semanal",   "https://github.com/trending/python?since=weekly"),
    ("Python — Trending mensal",    "https://github.com/trending/python?since=monthly"),
    ("TypeScript — Trending",       "https://github.com/trending/typescript?since=weekly"),
    ("Go — Trending",               "https://github.com/trending/go?since=weekly"),
    ("Rust — Trending",             "https://github.com/trending/rust?since=weekly"),
]

# READMEs de projetos arquitetais de referência
REFERENCE_REPOS = [
    ("FastAPI — Código Fonte",          "https://raw.githubusercontent.com/fastapi/fastapi/master/README.md"),
    ("SQLModel — ORM Pydantic+SQL",     "https://raw.githubusercontent.com/fastapi/sqlmodel/main/README.md"),
    ("Ruff — Linter Python",            "https://raw.githubusercontent.com/astral-sh/ruff/main/README.md"),
    ("uv — Python Package Manager",     "https://raw.githubusercontent.com/astral-sh/uv/main/README.md"),
    ("Polars — DataFrame Fast",         "https://raw.githubusercontent.com/pola-rs/polars/main/README.md"),
    ("Pydantic — Validação",            "https://raw.githubusercontent.com/pydantic/pydantic/main/README.md"),
    ("Typer — CLI com tipos",           "https://raw.githubusercontent.com/fastapi/typer/master/README.md"),
    ("LangGraph — Agents",             "https://raw.githubusercontent.com/langchain-ai/langgraph/main/README.md"),
    ("Instructor — LLM structured",     "https://raw.githubusercontent.com/jxnl/instructor/main/README.md"),
    ("Loguru — Python Logging",         "https://raw.githubusercontent.com/Delgan/loguru/master/README.md"),
    ("Tenacity — Retry lib",            "https://raw.githubusercontent.com/jd/tenacity/main/README.md"),
    ("httpx — Async HTTP",              "https://raw.githubusercontent.com/encode/httpx/master/README.md"),
    ("Celery — Task queue",             "https://raw.githubusercontent.com/celery/celery/main/README.rst"),
    ("Alembic — Migrations",            "https://raw.githubusercontent.com/sqlalchemy/alembic/main/README.rst"),
    ("pytest — Testing",                "https://raw.githubusercontent.com/pytest-dev/pytest/main/README.rst"),
    ("Prefect — Workflows",             "https://raw.githubusercontent.com/PrefectHQ/prefect/main/README.md"),
    ("DuckDB — Analytics",              "https://raw.githubusercontent.com/duckdb/duckdb/main/README.md"),
    ("Qdrant — Vector DB",              "https://raw.githubusercontent.com/qdrant/qdrant/master/README.md"),
    ("Temporal — Workflows",            "https://raw.githubusercontent.com/temporalio/temporal/main/README.md"),
    ("ArgoCD — GitOps",                 "https://raw.githubusercontent.com/argoproj/argo-cd/master/README.md"),
]


async def _fetch_github_trending(url: str) -> list[dict]:
    """Extrai repositórios trending da página do GitHub."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; APOLO-AI/2.0; research)"}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

        soup = BeautifulSoup(resp.text, "html.parser")
        repos = []
        for article in soup.select("article.Box-row")[:5]:
            h2 = article.select_one("h2 a")
            if not h2:
                continue
            name = h2.get_text(strip=True).replace("\n", "").replace(" ", "")
            desc_el = article.select_one("p")
            desc = desc_el.get_text(strip=True) if desc_el else ""
            lang_el = article.select_one("[itemprop='programmingLanguage']")
            lang = lang_el.get_text(strip=True) if lang_el else ""
            stars_el = article.select_one("a[href*='stargazers']")
            stars = stars_el.get_text(strip=True) if stars_el else ""
            repos.append({
                "name": name,
                "url": f"https://github.com/{name}",
                "description": desc,
                "language": lang,
                "stars": stars,
            })
        return repos
    except Exception as e:
        logger.debug(f"[github_agent] Trending fetch error: {e}")
        return []


class GitHubAgent(BaseAgent):
    """Agente que aprende com repositórios reais do GitHub."""

    name = "github_agent"
    category = "github"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trend_index = 0
        self._ref_index = 0
        # Alterna entre trending e referências
        self._mode_counter = 0

    async def next_topic(self) -> tuple[str, str]:
        self._mode_counter += 1
        if self._mode_counter % 3 == 0:
            # Trending do GitHub
            label, url = GITHUB_TRENDING_URLS[self._trend_index % len(GITHUB_TRENDING_URLS)]
            self._trend_index += 1
            return label, url
        else:
            # README de projeto de referência
            label, url = REFERENCE_REPOS[self._ref_index % len(REFERENCE_REPOS)]
            self._ref_index += 1
            return label, url

    async def _study(self, topic: str, url: str) -> StudyResult:
        logger.info(f"[github_agent] Estudando: {topic} — {url}")

        if "trending" in url:
            return await self._study_trending(topic, url)
        else:
            return await self._study_readme(topic, url)

    async def _study_trending(self, topic: str, url: str) -> StudyResult:
        repos = await asyncio.wait_for(_fetch_github_trending(url), timeout=15.0)
        if not repos:
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)

        content = f"# Repositórios em Alta — {topic}\n\n"
        for r in repos:
            content += f"## {r['name']}\n"
            content += f"- Linguagem: {r['language']}\n"
            content += f"- Estrelas: {r['stars']}\n"
            content += f"- Descrição: {r['description']}\n"
            content += f"- URL: {r['url']}\n\n"

        summary = await self.summarize(f"GitHub Trending — {topic}", content)
        return StudyResult(
            ok=True, topic=f"GitHub Trending: {topic}",
            url=url, summary=summary,
            category=self.category, agent_name=self.name,
        )

    async def _study_readme(self, topic: str, url: str) -> StudyResult:
        """Lê README de um projeto de referência."""
        headers = {"User-Agent": "Mozilla/5.0 (compatible; APOLO-AI/2.0; research)"}
        try:
            async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code != 200:
                    return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)
                content = resp.text[:5000]
        except Exception as e:
            logger.warning(f"[github_agent] Readme fetch error {url}: {e}")
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)

        if not content or len(content) < 100:
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)

        summary = await self.summarize(topic, content)
        return StudyResult(
            ok=True, topic=topic, url=url,
            summary=summary, category=self.category, agent_name=self.name,
        )
