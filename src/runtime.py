"""Estado compartilhado em runtime — os singletons criados no startup do app.

Preenchido por `app.py` no lifespan (via `configure`) e lido pelos routers.
Isto quebra o import circular da modularização: os routers importam ESTE módulo
(nunca `app.py`) e leem os atributos **em tempo de requisição**, quando já foram
populados no startup. Enquanto o singleton não é migrado, ele permanece também
como global em app.py — as duas referências apontam para o mesmo objeto.

Parte da modularização M1 do JARVIS_ROADMAP.
"""
from __future__ import annotations

from typing import Any, Callable

# Getter do modelo de chat: CHAT_MODEL é REATRIBUÍDO em runtime (o scheduler
# re-seleciona o modelo leve quando o Ollama volta). Um getter lê sempre o valor
# atual — guardar a string direto no runtime a deixaria stale após a troca.
get_chat_model: Callable[[], str | None] = lambda: None
# VISION_MODEL também é resolvido no startup (depois do configure) → getter.
get_vision_model: Callable[[], str | None] = lambda: None

# Modelo pesado (14b): constante de env, definida no import — nunca reatribuída.
model: Any = None

# Singletons (None até o startup do app popular via configure()).
learner: Any = None
db: Any = None
knowledge_db: Any = None
rag: Any = None
profile: Any = None
curator: Any = None
ingestor: Any = None
project_mem: Any = None
coder_ws: Any = None
# Dicts mutáveis compartilhados com o chat (mutados in-place, nunca reatribuídos):
# o router lê a MESMA referência que o chat muta.
sessions: Any = None
session_summaries: Any = None


def configure(**objects: Any) -> None:
    """Registra os singletons de runtime. Chamado uma vez, no startup do app."""
    globals().update(objects)
