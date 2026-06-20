"""Agente de Livros — aprende as ideias centrais de livros de não-ficção influentes.

Busca resumos/ideias-chave de clássicos de psicologia, hábitos, filosofia, negócios,
ciência e história. Foco em sabedoria aplicável, fora do código.
"""

import logging
import random

from src.web_search import web_research
from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

BOOKS: list[str] = [
    "Hábitos Atômicos (James Clear)",
    "Rápido e Devagar (Daniel Kahneman)",
    "Mindset (Carol Dweck)",
    "O Poder do Hábito (Charles Duhigg)",
    "Sapiens (Yuval Noah Harari)",
    "Como Fazer Amigos e Influenciar Pessoas (Dale Carnegie)",
    "O Homem em Busca de Sentido (Viktor Frankl)",
    "Inteligência Emocional (Daniel Goleman)",
    "Essencialismo (Greg McKeown)",
    "Antifrágil (Nassim Taleb)",
    "A Lógica do Cisne Negro (Nassim Taleb)",
    "Deep Work (Cal Newport)",
    "Os 7 Hábitos das Pessoas Altamente Eficazes (Stephen Covey)",
    "Pai Rico, Pai Pobre (Robert Kiyosaki)",
    "A Psicologia Financeira (Morgan Housel)",
    "Comece pelo Porquê (Simon Sinek)",
    "Meditações (Marco Aurélio)",
    "A Arte da Guerra (Sun Tzu)",
    "Flow (Mihaly Csikszentmihalyi)",
    "O Gene Egoísta (Richard Dawkins)",
]


class BookAgent(BaseAgent):
    """Estuda as ideias centrais de livros de não-ficção influentes."""

    name = "book_club"
    category = "books"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._shuffled = list(BOOKS)
        random.shuffle(self._shuffled)
        self._index = 0

    async def next_topic(self) -> tuple[str, str]:
        if self._index >= len(self._shuffled):
            self._index = 0
            random.shuffle(self._shuffled)
        book = self._shuffled[self._index]
        self._index += 1
        return f"Ideias centrais do livro {book}", ""

    async def _study(self, topic: str, _: str) -> StudyResult:
        logger.info(f"[book_club] {topic}")
        try:
            web_context, sources = await web_research(topic, max_results=3)
        except Exception as e:
            logger.warning(f"[book_club] '{topic}': {e}")
            return StudyResult(ok=False, topic=topic, agent_name=self.name)
        if not web_context or not sources:
            return StudyResult(ok=False, topic=topic, agent_name=self.name)
        summary = await self.summarize(topic, web_context)
        return StudyResult(ok=True, topic=topic, url=sources[0]["url"],
                           summary=summary, category=self.category, agent_name=self.name)
