"""Agente de tendências — monitora novidades tech e GitHub trending."""

import logging
import random

from src.web_search import web_research
from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

# ── Buscas de tendências — rotacionam entre si ───────────────
TREND_QUERIES: list[str] = [
    # Novidades Python
    "Python 3.13 new features release notes",
    "Python 3.14 new features proposals",
    "PEP 703 nogil Python free-threaded progress",
    "Python packaging uv pip replacement 2024",
    "Rye Python project manager tutorial",

    # Frameworks emergentes
    "Litestar Python ASGI framework vs FastAPI 2024",
    "FastStream Python event-driven framework",
    "Robyn Python web framework Rust performance",
    "Piccolo ORM Python async tutorial",
    "Beanie MongoDB async ODM Python tutorial",

    # IA & LLMs
    "Ollama local LLM deployment production",
    "LangChain vs LlamaIndex vs raw API 2024",
    "LangGraph agentic workflow Python tutorial",
    "RAG retrieval augmented generation best practices 2024",
    "Vector database comparison Chroma Qdrant Weaviate 2024",
    "Small language models SLM production Python",
    "Function calling tool use LLM Python patterns",
    "AI agent orchestration patterns Python",
    "Embeddings optimization production Python",
    "Prompt engineering advanced techniques 2024",

    # Cloud tendências
    "Serverless Python cold start reduction strategies 2024",
    "Platform engineering internal developer platform 2024",
    "FinOps cloud cost optimization Python tooling",
    "WebAssembly WASM Python server-side 2024",
    "Edge computing Python Cloudflare Workers",

    # Data & Analytics
    "DuckDB vs Spark small data Python analytics",
    "Polars vs Pandas performance Python 2024",
    "Streaming data processing Python Kafka Faust",
    "Feature store ML Python production 2024",
    "Data contracts schema evolution Python",

    # Segurança tendências
    "Supply chain security Python packages SBOM 2024",
    "Zero trust architecture Python application",
    "Container security scanning Python CI/CD",

    # Arquitetura tendências
    "Event-driven architecture Python 2024 patterns",
    "Backend for Frontend BFF pattern Python",
    "API gateway patterns Python microservices",
    "Service mesh alternative Python eBPF",
    "Temporal workflow Python durable execution",

    # DevEx & Ferramentas
    "Python type checking Pyright vs mypy 2024",
    "Nix flakes Python reproducible environments",
    "DevContainers Python development 2024",
    "Pydantic v2 migration guide performance",

    # Autonomia Total & IA Inteligente (missão A.P.O.L.O.)
    "autonomous AI agents 2024 state of the art",
    "AI agent frameworks AutoGen CrewAI LangGraph comparison 2024",
    "OpenAI Swarm multi-agent Python tutorial",
    "LLM agent memory architectures production 2024",
    "self-healing infrastructure AI autonomous Python",
    "AI code review autonomous agent Python GitHub",
    "autonomous data analysis AI agent Python pandas",
    "LLM tool use code interpreter autonomous Python",
    "AI agent safety alignment autonomous systems 2024",
    "personal AI assistant autonomous local Python JARVIS",
    "AI self-improvement techniques 2024 research",
    "autonomous scientific discovery AI Python",
    "AI agent benchmark evaluation AutoEval Python",
    "cognitive architecture AI agent BDI Python",

    # ── Frontend & Web ──
    "React 19 actions and use hook 2024",
    "signals reactivity frontend frameworks 2024",
    "CSS container queries and :has() 2024",
    "htmx hypermedia driven applications trend",

    # ── Mobile ──
    "Kotlin Multiplatform Compose 2024",
    "Flutter vs React Native 2024 comparison",

    # ── Linguagens & Sistemas ──
    "Rust adoption systems programming 2024",
    "Zig language vs Rust vs C 2024",
    "WebAssembly server-side WASI 2024",

    # ── Segurança ──
    "passkeys passwordless authentication adoption 2024",
    "post-quantum cryptography migration 2024",

    # ── Outros setores ──
    "edge computing and edge AI trends 2024",
    "blockchain layer 2 rollups scaling 2024",
    "game engines Godot growth 2024",
]


class TrendAgent(BaseAgent):
    """Agente que rastreia tendências e novidades tecnológicas."""

    name = "trend_radar"
    category = "tech_trend"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = 0
        # Shuffle inicial para variação entre reinicializações
        self._shuffled = list(TREND_QUERIES)
        random.shuffle(self._shuffled)

    async def next_topic(self) -> tuple[str, str]:
        if self._index >= len(self._shuffled):
            self._index = 0
            random.shuffle(self._shuffled)
        topic = self._shuffled[self._index]
        self._index += 1
        return topic, ""

    async def _study(self, topic: str, _: str) -> StudyResult:
        logger.info(f"[trend_radar] Monitorando tendência: {topic}")
        try:
            web_context, sources = await web_research(topic, max_results=3)
        except Exception as e:
            logger.warning(f"[trend_radar] Falha '{topic}': {e}")
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        if not web_context or not sources:
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        url = sources[0]["url"]
        summary = await self.summarize(f"Tendência: {topic}", web_context)
        return StudyResult(
            ok=True, topic=f"[Tendência] {topic}", url=url,
            summary=summary, category=self.category, agent_name=self.name,
        )
