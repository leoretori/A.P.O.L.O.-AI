"""Agente de síntese — conecta tópicos aprendidos e gera insights cross-domain."""

import asyncio
import logging

from src.llm import chat_resilient

from .base import BaseAgent, StudyResult

logger = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """Você é o Apolo, arquiteto de sistemas sênior com visão holística.

Você acabou de estudar os seguintes tópicos técnicos recentemente:

{topics_list}

Agora crie uma SÍNTESE ESTRATÉGICA que:

## Padrões Comuns
[Identifique 3-4 padrões que aparecem em múltiplos tópicos acima]

## Arquitetura Integrada
[Como esses componentes se encaixam numa stack real de produção — desenhe a integração]

## Decisões Arquiteturais
[Quando usar cada tecnologia — trade-offs concretos e critérios de escolha]

## Próximos Estudos Recomendados
[3 tópicos que complementariam este conhecimento — seja específico]

## Insight do Apolo
[Sua observação mais importante sobre como esses sistemas funcionam juntos]

Síntese em português brasileiro — seja estratégico, não apenas descritivo:"""


class SynthesisAgent(BaseAgent):
    """Agente que sintetiza conhecimento cross-domain a partir do histórico."""

    name = "synthesizer"
    category = "synthesis"

    # Só roda a cada N ciclos dos outros agentes
    SYNTHESIS_EVERY_N = 5

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cycle_count = 0

    def should_run(self) -> bool:
        """Retorna True a cada N ciclos."""
        self._cycle_count += 1
        return self._cycle_count % self.SYNTHESIS_EVERY_N == 0

    async def next_topic(self) -> tuple[str, str]:
        return "Síntese cross-domain", ""

    async def _study(self, topic: str, _: str) -> StudyResult:
        if not self.db:
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        # Busca últimos tópicos aprendidos
        history = self.db.get_learning_history(limit=10)
        if len(history) < 3:
            logger.info("[synthesizer] Poucos tópicos ainda — aguardando mais aprendizado")
            return StudyResult(ok=False, topic=topic, agent_name=self.name)

        topics_list = "\n".join(
            f"- [{h['category']}] {h['topic']}" for h in history[:10]
        )

        topic_label = "Síntese: " + " + ".join(
            h["topic"].split()[:2] for h in history[:3]
        )

        logger.info(f"[synthesizer] Sintetizando {len(history)} tópicos")
        self.current_topic = topic_label

        prompt = SYNTHESIS_PROMPT.format(topics_list=topics_list)
        try:
            synthesis = await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient,
                    self.model,
                    [{"role": "user", "content": prompt}],
                ),
                timeout=180.0,
            )
        except Exception as e:
            logger.warning(f"[synthesizer] Erro: {e}")
            return StudyResult(ok=False, topic=topic_label, agent_name=self.name)

        url = f"synthesis://local/{hash(topics_list) & 0xFFFF:04x}"
        return StudyResult(
            ok=True,
            topic=topic_label,
            url=url,
            summary=synthesis,
            category=self.category,
            agent_name=self.name,
        )
