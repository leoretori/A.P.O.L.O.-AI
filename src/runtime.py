"""Estado compartilhado em runtime — os singletons criados no startup do app.

Preenchido por `app.py` no lifespan (via `configure`) e lido pelos routers.
Isto quebra o import circular da modularização: os routers importam ESTE módulo
(nunca `app.py`) e leem os atributos **em tempo de requisição**, quando já foram
populados no startup. Enquanto o singleton não é migrado, ele permanece também
como global em app.py — as duas referências apontam para o mesmo objeto.

Parte da modularização M1 do JARVIS_ROADMAP.
"""
from __future__ import annotations

from typing import Any

# Singletons (None até o startup do app popular via configure()).
learner: Any = None
db: Any = None
knowledge_db: Any = None


def configure(**objects: Any) -> None:
    """Registra os singletons de runtime. Chamado uma vez, no startup do app."""
    globals().update(objects)
