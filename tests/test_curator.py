"""Testes do Curador de Memória (detecção e remoção de duplicatas)."""

from src.curator import MemoryCurator, _norm_title


class _FakeKnowledge:
    def __init__(self, rows):
        self._rows = rows
        self.deleted = None

    def all_rows(self, limit=1000):
        return self._rows

    def delete_ids(self, ids):
        self.deleted = list(ids)
        return len(ids)


def _row(id_, title, content=None, category="web_search", url=""):
    # Conteúdo distinto por padrão — assim só a dedup por TÍTULO age, salvo quando
    # o teste passa conteúdo igual de propósito.
    body = content if content is not None else f"conteúdo distinto do registro {id_} " * 3
    return {"id": id_, "title": title, "url": url or f"http://x/{id_}",
            "content": body, "category": category, "updated_at": "2026-01-01"}


def test_norm_title_remove_ruido():
    assert _norm_title("[A.P.O.L.O.] Python Asyncio (parte 2/3)") == "python asyncio"


def test_scan_detecta_titulo_duplicado():
    rows = [
        _row("1", "[A.P.O.L.O.] Python metaclasses",
             content="metaclasses customizam a criação de classes via type e __new__"),
        _row("2", "[A.P.O.L.O.] Python metaclasses",   # mesmo título → dup (conteúdo distinto)
             content="registro automático de subclasses usando hooks de metaclasse"),
        _row("3", "[A.P.O.L.O.] Kubernetes HPA",
             content="o HPA escala réplicas de pods conforme CPU e memória observadas"),
    ]
    d = MemoryCurator(knowledge_db=_FakeKnowledge(rows)).scan()
    assert d["total"] == 3
    assert d["duplicate_clusters"] == 1
    assert d["removable"] == 1


def test_scan_detecta_conteudo_quase_identico():
    base = "Texto técnico denso sobre otimização de performance " * 10
    rows = [
        _row("1", "Guia A", content=base),
        _row("2", "Guia B", content=base + " pequeno ajuste"),  # ~igual → dup
    ]
    d = MemoryCurator(knowledge_db=_FakeKnowledge(rows)).scan()
    assert d["removable"] == 1


def test_scan_mantem_o_mais_completo():
    rows = [
        _row("curto", "Mesmo Tópico", content="curto"),
        _row("longo", "Mesmo Tópico", content="conteúdo bem mais longo e completo " * 5),
    ]
    d = MemoryCurator(knowledge_db=_FakeKnowledge(rows)).scan()
    cluster = d["clusters"][0]
    assert cluster["keeper"]["id"] == "longo"
    assert cluster["dupes"][0]["id"] == "curto"


def test_apply_remove_ids():
    kb = _FakeKnowledge([])
    res = MemoryCurator(knowledge_db=kb).apply(["a", "b"])
    assert res["removed"] == 2
    assert kb.deleted == ["a", "b"]


def test_base_pequena_sem_duplicatas():
    d = MemoryCurator(knowledge_db=_FakeKnowledge([_row("1", "Único")])).scan()
    assert d["duplicate_clusters"] == 0
    assert d["removable"] == 0
