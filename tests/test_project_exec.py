"""Execução supervisionada de projetos (M19.1): do propor ao fazer."""

from src.project_exec import (
    ExecContext,
    get_op,
    plan_for,
    preview_step,
    run_step,
)


class FakeDB:
    def __init__(self, quality=None, dups=0):
        self._quality = quality or {"pct_structured": 60, "raw": 4}
        self._dups = dups
        self.deduped = False

    def get_summary_quality(self):
        return dict(self._quality)

    def count_topic_duplicates(self):
        return 0 if self.deduped else self._dups

    def dedup_learned_topics(self):
        n = 0 if self.deduped else self._dups
        self.deduped = True
        return n


class FakeRag:
    def __init__(self, dups=0):
        self._dups = dups
        self.deleted = False

    def dedup_exact(self, dry_run=False):
        if dry_run:
            return self._dups
        if not self.deleted:
            self.deleted = True
            return self._dups
        return 0


def _ctx(db=None, rag=None):
    return ExecContext(db=db or FakeDB(), rag=rag or FakeRag())


def test_plan_por_tipo():
    plan = plan_for({"kind": "dedup"})
    keys = [s["key"] for s in plan]
    assert keys == ["measure_duplicates", "dedup_topics", "dedup_index"]
    assert all(s["executable"] for s in plan)


def test_plan_tipo_sem_execucao_fica_manual():
    assert plan_for({"kind": "gaps"}) == []
    assert plan_for({"kind": "desconhecido"}) == []


def test_medicao_nao_muta():
    op = get_op("measure_summary_quality")
    assert op.mutates is False
    pv = preview_step("measure_summary_quality", _ctx())
    assert pv["ok"] and "não muda" in pv["preview"]["summary"].lower()
    out = run_step("measure_summary_quality", _ctx())
    assert out["ok"] and out["mutated"] is False
    assert out["measure"]["pct_structured"] == 60


def test_preview_dedup_conta_sem_apagar():
    db = FakeDB(dups=7)
    pv = preview_step("dedup_topics", _ctx(db=db))
    assert pv["ok"] and pv["mutates"] is True
    assert pv["preview"]["count"] == 7
    assert db.deduped is False        # prévia NÃO apagou nada


def test_run_dedup_topics_remede():
    db = FakeDB(dups=7)
    out = run_step("dedup_topics", _ctx(db=db))
    assert out["ok"] and out["result"]["removed"] == 7
    assert out["measure"]["duplicates"] == 0   # re-mediu: zerou
    assert db.deduped is True


def test_run_dedup_index_dry_run_no_preview():
    rag = FakeRag(dups=3)
    pv = preview_step("dedup_index", _ctx(rag=rag))
    assert pv["preview"]["count"] == 3 and rag.deleted is False
    out = run_step("dedup_index", _ctx(rag=rag))
    assert out["ok"] and out["result"]["removed"] == 3 and rag.deleted is True


def test_passo_desconhecido():
    assert preview_step("nao_existe", _ctx())["ok"] is False
    assert run_step("nao_existe", _ctx())["ok"] is False
