"""Agente de busca na web — DuckDuckGo + sumarização LLM.

Estuda em LEQUE: percorre dezenas de setores (tech + conhecimento geral) em
rodízio, definidos em `src/topics.py` — então não afunda num só assunto.
"""

import logging

from src.topics import ALL_TOPICS
from src.web_search import web_research
from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

# Universo multissetorial, já intercalado por setor (ver src/topics.py).
SEARCH_TOPICS: list[str] = ALL_TOPICS


class WebSearchAgent(BaseAgent):
    """Agente que busca tópicos via DuckDuckGo e sumariza com LLM."""

    name = "web_search"
    category = "web_search"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._index = 0

    async def next_topic(self) -> tuple[str, str]:
        topic = SEARCH_TOPICS[self._index % len(SEARCH_TOPICS)]
        self._index += 1
        return topic, ""

    async def _study(self, topic: str, _: str) -> StudyResult:
        logger.info(f"[web_search] Buscando: {topic}")
        try:
            web_context, sources = await web_research(topic, max_results=2)
        except Exception as e:
            logger.warning(f"[web_search] Falha na busca '{topic}': {e}")
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        if not web_context or not sources:
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        url = sources[0]["url"]
        summary = await self.summarize(topic, web_context)
        return StudyResult(
            ok=True, topic=topic, url=url,
            summary=summary, category=self.category, agent_name=self.name,
        )
