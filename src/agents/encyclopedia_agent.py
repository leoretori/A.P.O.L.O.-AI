"""Agente de Enciclopédia — aprende conhecimento geral (não-tech) na Wikipédia.

Crawl direto em artigos da Wikipédia em português sobre ciência, filosofia,
história, arte, saúde, sociedade... Amplia o A.P.O.L.O. para muito além de código.
"""

import logging
import random
from urllib.parse import quote

from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

# Assuntos enciclopédicos (pt.wikipedia) — amplo espectro de conhecimento humano.
WIKI_SUBJECTS: list[str] = [
    # Ciência
    "Teoria da relatividade", "Mecânica quântica", "Fotossíntese", "Genética",
    "Evolução", "Termodinâmica", "Tabela periódica", "Buraco negro",
    "Big Bang", "Entropia", "Neurociência", "Microbiologia", "Antimatéria",
    # Saúde & corpo
    "Sistema imunológico", "Cérebro humano", "DNA", "Vacina", "Coração",
    "Sono", "Metabolismo", "Longevidade", "Nutrição",
    # Mente & sociedade
    "Inteligência emocional", "Psicanálise", "Estoicismo", "Democracia",
    "Capitalismo", "Economia comportamental", "Filosofia",
    "Teoria dos jogos", "Lógica", "Retórica", "Ética", "Antropologia",
    # História & cultura
    "Revolução Industrial", "Renascimento", "Iluminismo", "Segunda Guerra Mundial",
    "Império Romano", "Grécia Antiga", "Rota da Seda", "Idade Média",
    # Arte
    "Música", "Pintura", "Arquitetura", "Cinema", "Literatura", "Fotografia",
    # Planeta & espaço
    "Sistema solar", "Mudança climática", "Vulcão", "Oceano", "Sustentabilidade",
    "Via Láctea", "Exoplaneta", "Biodiversidade", "Amazônia",
]


class EncyclopediaAgent(BaseAgent):
    """Estuda artigos da Wikipédia (pt) — conhecimento geral além da tecnologia."""

    name = "encyclopedia"
    category = "encyclopedia"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Início aleatório: cada sessão explora uma região diferente da lista
        # (antes TODA sessão começava em "Teoria da relatividade").
        self._index = random.randrange(len(WIKI_SUBJECTS))

    async def next_topic(self) -> tuple[str, str]:
        # Avança pulando artigos já estudados (dedup por URL).
        attempts = 0
        while attempts < len(WIKI_SUBJECTS):
            subject = WIKI_SUBJECTS[self._index % len(WIKI_SUBJECTS)]
            self._index += 1
            attempts += 1
            url = f"https://pt.wikipedia.org/wiki/{quote(subject.replace(' ', '_'))}"
            if not (self.db and self.db.is_url_studied(url)):
                return f"{subject} (enciclopédia)", url
        # Tudo estudado — segue a rotação do ponto atual (antes resetava para o
        # índice 0 e o refresh caía SEMPRE no mesmo primeiro assunto da lista).
        subject = WIKI_SUBJECTS[self._index % len(WIKI_SUBJECTS)]
        self._index += 1
        return f"{subject} (enciclopédia)", \
            f"https://pt.wikipedia.org/wiki/{quote(subject.replace(' ', '_'))}"

    async def _study(self, topic: str, url: str) -> StudyResult:
        # O pipeline do learner faz o fetch+sumarização; mantido para compatibilidade
        # com run_cycle/study_now da BaseAgent.
        from src.web_search import fetch_page_text
        import asyncio
        try:
            content = await asyncio.wait_for(fetch_page_text(url), timeout=15.0)
        except Exception as e:
            logger.warning(f"[encyclopedia] fetch {url}: {e}")
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)
        if not content or len(content) < 100:
            return StudyResult(ok=False, topic=topic, url=url, agent_name=self.name)
        summary = await self.summarize(topic, content)
        return StudyResult(ok=True, topic=topic, url=url, summary=summary,
                           category=self.category, agent_name=self.name)
