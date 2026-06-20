"""Classe base para todos os mini-agentes de aprendizado do A.P.O.L.O."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime

from src.llm import chat_resilient

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """Você é A.P.O.L.O., agente de IA de elite especializado em engenharia de software.

Analise o conteúdo técnico abaixo sobre "{topic}" e produza uma síntese estruturada:

## Conceitos Fundamentais
[3-5 conceitos centrais explicados de forma direta e técnica]

## Implementação Prática
[Exemplo de código real ou passos concretos — production-ready]

## Padrões e Boas Práticas
[O que fazer e o que evitar — insights de engenheiro sênior]

## Integração com o Ecossistema
[Como este tópico se conecta com Docker, Kubernetes, cloud, CI/CD, bancos de dados, etc.]

---
CONTEÚDO FONTE:
{content}
---

Síntese técnica em português brasileiro (preciso, denso, sem enrolação):"""


class StudyResult:
    """Resultado padronizado de um ciclo de estudo."""

    def __init__(
        self,
        ok: bool,
        topic: str,
        url: str = "",
        summary: str = "",
        category: str = "web_search",
        agent_name: str = "",
    ):
        self.ok = ok
        self.topic = topic
        self.url = url
        self.summary = summary
        self.category = category
        self.agent_name = agent_name
        self.timestamp = datetime.now().strftime("%H:%M")

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "topic": self.topic,
            "url": self.url,
            "summary": self.summary,
            "category": self.category,
            "agent": self.agent_name,
            "time": self.timestamp,
        }


class BaseAgent(ABC):
    """Base para mini-agentes — encapsula fetch, sumarização e persistência."""

    name: str = "base"
    category: str = "web_search"

    def __init__(self, model: str, rag=None, knowledge_db=None, db=None):
        self.model = model
        self.rag = rag
        self.knowledge_db = knowledge_db
        self.db = db
        self.active = False
        self.current_topic = ""

    @abstractmethod
    async def next_topic(self) -> tuple[str, str]:
        """Retorna (topic, url_hint) — url_hint pode ser vazio para buscas."""
        ...

    async def run_cycle(self) -> StudyResult:
        """Executa um ciclo completo: escolhe tópico → busca → sumariza → salva."""
        self.active = True
        try:
            topic, url_hint = await self.next_topic()
            self.current_topic = topic
            result = await self._study(topic, url_hint)
            if result.ok:
                await self._persist(result)
            return result
        except Exception as e:
            logger.error(f"[{self.name}] Erro no ciclo: {e}", exc_info=True)
            return StudyResult(ok=False, topic=self.current_topic, agent_name=self.name)
        finally:
            self.active = False
            self.current_topic = ""

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "active": self.active,
            "current_topic": self.current_topic,
        }

    @abstractmethod
    async def _study(self, topic: str, url_hint: str) -> StudyResult:
        ...

    async def summarize(self, topic: str, content: str) -> str:
        """Sumariza conteúdo com Ollama — o cérebro do A.P.O.L.O."""
        prompt = SUMMARIZE_PROMPT.format(topic=topic, content=content[:4000])
        try:
            summary = await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient,
                    self.model,
                    [{"role": "user", "content": prompt}],
                ),
                timeout=150.0,
            )
            logger.info(f"[{self.name}] Síntese: {len(summary)} chars — {topic[:50]}")
            return summary
        except asyncio.TimeoutError:
            logger.warning(f"[{self.name}] Timeout na síntese de '{topic}'")
            return content[:2000]
        except Exception as e:
            logger.warning(f"[{self.name}] Erro na síntese: {e}")
            return content[:2000]

    async def _persist(self, result: StudyResult) -> None:
        """Salva em SQLite + Supabase + ChromaDB."""
        tasks = []

        if self.db:
            tasks.append(asyncio.to_thread(
                self.db.save_learned_topic,
                result.topic, result.url, result.summary[:2000], result.category,
            ))

        if self.knowledge_db:
            tasks.append(asyncio.to_thread(
                self.knowledge_db.save,
                f"[A.P.O.L.O.] {result.topic}",
                result.url,
                result.summary,
                result.category,
            ))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[{self.name}] Erro ao persistir: {r}")

        if self.rag and result.summary:
            try:
                doc_id = f"{self.name}_{hash(result.url or result.topic) & 0xFFFFFFFF:08x}"
                await asyncio.to_thread(
                    self.rag.add_example,
                    f"# {result.topic}\nFonte: {result.url}\n\n{result.summary}",
                    doc_id,
                )
            except Exception as e:
                logger.warning(f"[{self.name}] Erro no ChromaDB: {e}")

        logger.info(f"[{self.name}] ✓ '{result.topic[:50]}'")
