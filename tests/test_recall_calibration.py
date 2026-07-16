"""Instrumento de calibração de MEMORY_MIN_RELEVANCE: mede a distribuição REAL
de scores contra perguntas reais — não muda nada, só relatório."""
import pytest

from src.recall_calibration import (
    calibrate,
    evaluate_recall_gate,
    freeze_ground_truth,
    read_recall_gate_history,
    run_tracked_recall_gate,
)


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


# ── Gate de regressão do recall (P2.6) ──────────────────────────
class _FakeDBTopics:
    def __init__(self, topics):
        self._topics = topics

    def sample_topics_for_quality(self, n=15):
        return [{"id": i, "topic": t, "summary": "x"} for i, t in enumerate(self._topics[:n])]


class _FakeRagRecall:
    """`recall(topic)` acha o próprio tópico, exceto os listados em `esquecidos`."""
    def __init__(self, esquecidos=()):
        self._esquecidos = set(esquecidos)

    def recall(self, query, n_results=5):
        if query in self._esquecidos:
            return [{"title": "coisa completamente diferente"}]
        return [{"title": query}, {"title": "outro resultado qualquer"}]


def test_freeze_ground_truth_congela_e_e_idempotente(tmp_path):
    db = _FakeDBTopics([f"Tópico {i}" for i in range(20)])
    path = tmp_path / "gt.json"
    gt1 = freeze_ground_truth(db, path, n=15, min_topics=10)
    assert len(gt1) == 15

    db2 = _FakeDBTopics([f"Outro bem diferente {i}" for i in range(20)])
    gt2 = freeze_ground_truth(db2, path, n=15, min_topics=10)
    assert gt2 == gt1  # não re-sorteou mesmo com a base tendo "mudado"


def test_freeze_ground_truth_poucos_topicos_levanta_erro(tmp_path):
    db = _FakeDBTopics([f"T{i}" for i in range(5)])
    with pytest.raises(ValueError, match="poucos tópicos"):
        freeze_ground_truth(db, tmp_path / "gt.json", n=30, min_topics=10)


def test_freeze_ground_truth_deduplica(tmp_path):
    db = _FakeDBTopics(["A", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J"])
    gt = freeze_ground_truth(db, tmp_path / "gt.json", n=5, min_topics=2)
    assert len(gt) == len(set(gt))  # sem repetição, mesmo com "A" duplicado na fonte


def test_evaluate_recall_gate_mede_hit_rate():
    gt = ["Kafka", "Redis", "Postgres"]
    rag = _FakeRagRecall(esquecidos=["Redis"])
    res = evaluate_recall_gate(rag, gt, k=5)
    assert res["status"] == "ok"
    assert res["n"] == 3
    assert res["hits"] == 2
    assert res["hit_rate"] == pytest.approx(66.7, abs=0.1)
    assert res["misses"] == ["Redis"]


def test_evaluate_recall_gate_sem_conjunto():
    res = evaluate_recall_gate(_FakeRagRecall(), [])
    assert res == {"status": "skipped", "reason": "sem conjunto congelado"}


def test_evaluate_recall_gate_erro_no_recall_conta_como_falha():
    class _Boom:
        def recall(self, *a, **k):
            raise RuntimeError("índice fora do ar")
    res = evaluate_recall_gate(_Boom(), ["Kafka"])
    assert res["status"] == "ok"
    assert res["hits"] == 0
    assert res["misses"] == ["Kafka"]


def test_run_tracked_recall_gate_registra_historico(tmp_path):
    db = _FakeDBTopics([f"Tópico {i}" for i in range(20)])
    rag = _FakeRagRecall()
    gt_path, hist_path = tmp_path / "gt.json", tmp_path / "hist.jsonl"
    res = run_tracked_recall_gate(db, rag, ground_truth_path=gt_path,
                                  history_path=hist_path, n=15, min_topics=10)
    assert res["status"] == "ok"
    hist = read_recall_gate_history(hist_path)
    assert len(hist) == 1 and hist[0]["hits"] == res["hits"]

    # 2ª rodada usa o MESMO conjunto congelado e acrescenta ao histórico
    run_tracked_recall_gate(db, rag, ground_truth_path=gt_path,
                            history_path=hist_path, n=15, min_topics=10)
    assert len(read_recall_gate_history(hist_path)) == 2


def test_read_recall_gate_history_arquivo_inexistente(tmp_path):
    assert read_recall_gate_history(tmp_path / "nao_existe.jsonl") == []
