"""Execução supervisionada de projetos (M19.1): do propor ao fazer."""

from src.project_exec import (
    ExecContext,
    capture_baseline,
    get_op,
    metric_for,
    outcome,
    plan_for,
    preview_step,
    run_plan,
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


# ───────────────────────────── M19.2 plano multi-passo ──────────────────────
def test_plano_para_no_primeiro_passo_sensivel():
    # dedup: [measure_duplicates(read), dedup_topics(mut), dedup_index(mut)]
    db, rag = FakeDB(dups=5), FakeRag(dups=2)
    out = run_plan({"kind": "dedup"}, _ctx(db=db, rag=rag))
    assert out["status"] == "needs_confirmation"
    assert out["checkpoint"] == "dedup_topics"       # parou na 1ª mutação
    assert [r["key"] for r in out["ran"]] == ["measure_duplicates"]  # rodou a medição
    assert db.deduped is False                        # NÃO mutou sem confirmar
    assert out["preview"]["count"] == 5


def test_plano_confirma_passo_e_avanca_ao_proximo_checkpoint():
    db, rag = FakeDB(dups=5), FakeRag(dups=2)
    out = run_plan({"kind": "dedup"}, _ctx(db=db, rag=rag), confirm="dedup_topics")
    # rodou a medição + a mutação confirmada, e parou na PRÓXIMA mutação
    assert out["status"] == "needs_confirmation"
    assert out["checkpoint"] == "dedup_index"
    assert db.deduped is True and rag.deleted is False
    assert [r["key"] for r in out["ran"]] == ["measure_duplicates", "dedup_topics"]


def test_plano_pula_mutacao_ja_resolvida_idempotente():
    # sem duplicatas: as mutações re-medem 0 → puladas, plano conclui sozinho
    db, rag = FakeDB(dups=0), FakeRag(dups=0)
    out = run_plan({"kind": "dedup"}, _ctx(db=db, rag=rag))
    assert out["status"] == "done" and out["progress"] == 100
    skipped = [r["key"] for r in out["ran"] if r.get("skipped")]
    assert "dedup_topics" in skipped and "dedup_index" in skipped


def test_plano_vazio_para_tipo_manual():
    assert run_plan({"kind": "gaps"}, _ctx())["status"] == "empty"


# ───────────────────────────── M19.3 propõe→faz→mede ────────────────────────
def test_metric_e_baseline():
    db = FakeDB(dups=12)
    b = capture_baseline("dedup", _ctx(db=db))
    assert b["value"] == 12 and b["direction"] == "down"
    assert metric_for("summary_quality", _ctx())["direction"] == "up"


def test_metric_tipo_sem_metrica():
    assert metric_for("gaps", _ctx()) is None
    assert capture_baseline("gaps", _ctx()) is None


def test_outcome_melhorou_dedup():
    # baseline 12 duplicatas; agora 0 (down is better) → melhorou
    db = FakeDB(dups=0)
    proj = {"kind": "dedup", "baseline": {"value": 12, "direction": "down"}}
    o = outcome(proj, _ctx(db=db))
    assert o["measurable"] and o["baseline"] == 12 and o["current"] == 0
    assert o["delta"] == -12 and o["improved"] is True


def test_outcome_piorou_qualidade():
    # % estruturadas caiu de 80 para 60 (up is better) → não melhorou
    db = FakeDB(quality={"pct_structured": 60, "raw": 4})
    proj = {"kind": "summary_quality", "baseline": {"value": 80, "direction": "up"}}
    o = outcome(proj, _ctx(db=db))
    assert o["delta"] == -20 and o["improved"] is False


def test_outcome_estavel_e_nao_mensuravel():
    db = FakeDB(dups=5)
    proj = {"kind": "dedup", "baseline": {"value": 5}}
    assert outcome(proj, _ctx(db=db))["improved"] is None      # delta 0
    assert outcome({"kind": "gaps"}, _ctx())["measurable"] is False
