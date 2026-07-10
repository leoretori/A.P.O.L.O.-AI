"""Endpoints da memória relacional & temporal (M18).

/api/timeline — a linha do tempo da vida: episódios datados anotados com as
entidades (pessoas/projetos/metas) que tocaram, opcionalmente filtrados por
uma entidade ou por uma janela temporal ("semana passada").

Extraído no espírito da M1: lê os singletons de `src.runtime` em tempo de
requisição, nunca importa app.py.
"""
from fastapi import APIRouter

from src import runtime as rt

router = APIRouter()


@router.get("/api/timeline")
async def get_timeline(entity: str | None = None, when: str | None = None,
                       limit: int = 30):
    """Linha do tempo da vida (M18.1).

    - `when`: frase temporal ("ontem", "semana passada") → recorta a janela.
    - `entity`: nome de pessoa/projeto/meta → só os episódios que a tocaram.
    """
    ep = rt.episodic
    if not ep:
        return {"events": []}
    if when:
        eps = ep.recall_phrase(when)
        if eps is None:  # frase não era temporal → cai nos recentes
            eps = ep.recent(limit)
    else:
        eps = ep.recent(limit)
    from src.timeline import timeline
    return {"events": timeline(eps, rt.profile, entity=entity)}
