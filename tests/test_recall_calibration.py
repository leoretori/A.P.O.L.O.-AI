"""Instrumento de calibração de MEMORY_MIN_RELEVANCE: mede a distribuição REAL
de scores contra perguntas reais — não muda nada, só relatório."""
from src.recall_calibration import calibrate


class _Hit:
    def __init__(self, score):
        self.score = score


class _FakeMem:
    """Devolve scores fixos por query — permite montar cenários exatos."""
    def __init__(self, by_query: dict[str, list[float]]):
        self.by_query = by_query
        self.calls = []

    def recall(self, query, kind=None, limit=8):
        self.calls.append((query, kind, limit))
        return [_Hit(s) for s in self.by_query.get(query, [])]


def test_calibrate_agrega_scores_de_todas_as_perguntas(monkeypatch):
    monkeypatch.delenv("MEMORY_MIN_RELEVANCE", raising=False)
    mem = _FakeMem({"a": [0.1, 0.3], "b": [0.5]})
    res = calibrate(mem, ["a", "b"])
    assert res["scores_coletados"] == 3
    assert res["queries_amostradas"] == 2
    assert res["min"] == 0.1 and res["max"] == 0.5


def test_calibrate_conta_perguntas_sem_nenhum_resultado(monkeypatch):
    monkeypatch.delenv("MEMORY_MIN_RELEVANCE", raising=False)
    mem = _FakeMem({"tem": [0.4]})
    res = calibrate(mem, ["tem", "sem resultado"])
    assert res["queries_sem_nenhum_resultado"] == 1
    assert res["scores_coletados"] == 1


def test_calibrate_usa_kind_semantic_e_o_limit_pedido():
    mem = _FakeMem({"q": [0.2]})
    calibrate(mem, ["q"], n=5)
    assert mem.calls == [("q", "semantic", 5)]


def test_calibrate_conta_por_limiar_candidato(monkeypatch):
    monkeypatch.delenv("MEMORY_MIN_RELEVANCE", raising=False)
    mem = _FakeMem({"a": [0.05, 0.19, 0.20, 0.40]})
    res = calibrate(mem, ["a"], thresholds=(0.10, 0.20, 0.30))
    assert res["por_limiar_candidato"]["0.10"]["passariam"] == 3   # 0.19,0.20,0.40
    assert res["por_limiar_candidato"]["0.20"]["passariam"] == 2   # 0.20,0.40
    assert res["por_limiar_candidato"]["0.30"]["passariam"] == 1   # 0.40
    assert res["por_limiar_candidato"]["0.30"]["seriam_cortados"] == 3


def test_calibrate_le_o_limiar_atual_do_env(monkeypatch):
    monkeypatch.setenv("MEMORY_MIN_RELEVANCE", "0.25")
    mem = _FakeMem({"a": [0.1, 0.3, 0.5]})
    res = calibrate(mem, ["a"])
    assert res["limiar_atual"] == 0.25
    assert res["passariam_no_limiar_atual"] == 2   # 0.3 e 0.5


def test_calibrate_sem_perguntas_nao_quebra(monkeypatch):
    monkeypatch.delenv("MEMORY_MIN_RELEVANCE", raising=False)
    res = calibrate(_FakeMem({}), [])
    assert res["scores_coletados"] == 0
    assert res["min"] is None and res["max"] is None


def test_calibrate_ignora_recall_que_lanca_excecao():
    class _Boom:
        def recall(self, *a, **k):
            raise RuntimeError("índice fora do ar")
    res = calibrate(_Boom(), ["qualquer"])
    assert res["queries_sem_nenhum_resultado"] == 1
    assert res["scores_coletados"] == 0
