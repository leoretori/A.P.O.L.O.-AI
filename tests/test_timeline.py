"""Linha do tempo da vida (M18.1): episódios datados ligados às entidades."""

from src.timeline import _anchors, entities, link_event, timeline


class FakeProfile:
    def __init__(self, groups=None):
        self._g = groups or {}

    def by_category(self):
        return self._g


def _prof(persons=(), projects=(), goals=()):
    g = {}
    if persons:
        g["person"] = [{"fact": p, "category": "person", "id": f"p{i}"}
                       for i, p in enumerate(persons)]
    if projects:
        g["project"] = [{"fact": p, "category": "project", "id": f"pr{i}"}
                        for i, p in enumerate(projects)]
    if goals:
        g["goal"] = [{"fact": x, "category": "goal", "id": f"g{i}"}
                     for i, x in enumerate(goals)]
    return FakeProfile(g)


def _ep(title, summary="", occurred_at="2026-07-06T09:00:00", id="e1"):
    return {"id": id, "title": title, "summary": summary, "occurred_at": occurred_at}


def test_anchors_pega_nome_proprio():
    assert _anchors("Maria, minha irmã") == {"maria"}
    assert _anchors("Apolo AI em python") == {"apolo", "ai"}
    # capitalizadas comuns não viram âncora
    assert _anchors("Quero aprender rust") == set()


def test_entities_extrai_por_categoria():
    prof = _prof(persons=["Maria"], projects=["Apolo AI"], goals=["aprender rust"])
    ents = entities(prof)
    cats = {e["category"] for e in ents}
    assert cats == {"person", "project", "goal"}
    maria = next(e for e in ents if e["name"] == "Maria")
    assert maria["anchors"] == {"maria"}


def test_link_por_nome_proprio():
    prof = _prof(persons=["Maria, minha irmã"])
    ev = link_event(_ep("Almoço", "A Maria me pediu ajuda com o currículo"),
                    entities(prof))
    assert ev["refs"].get("person") == ["Maria, minha irmã"]


def test_link_por_conceito_sem_nome_proprio():
    # meta minúscula ("aprender rust") liga por conceito partilhado (grafo)
    prof = _prof(goals=["aprender rust"])
    ev = link_event(_ep("Estudo", "estudei ownership em rust hoje"), entities(prof))
    assert ev["refs"].get("goal") == ["aprender rust"]


def test_nao_liga_episodio_sem_relacao():
    prof = _prof(persons=["Maria"], goals=["aprender rust"])
    ev = link_event(_ep("Cozinha", "fiz uma receita de bolo de cenoura"),
                    entities(prof))
    assert ev["refs"] == {}


def test_timeline_filtra_por_entidade():
    prof = _prof(projects=["Apolo AI"], persons=["Maria"])
    eps = [
        _ep("Deploy", "subimos o Apolo AI em produção", id="a"),
        _ep("Almoço", "conversa com a Maria", id="b"),
    ]
    tl = timeline(eps, prof, entity="apolo")
    assert [ev["id"] for ev in tl] == ["a"]
    assert tl[0]["date"] == "2026-07-06T09:00:00"


def test_timeline_sem_profile():
    assert timeline([_ep("x")], None) == [{
        "id": "e1", "date": "2026-07-06T09:00:00", "title": "x",
        "summary": "", "refs": {},
    }]
