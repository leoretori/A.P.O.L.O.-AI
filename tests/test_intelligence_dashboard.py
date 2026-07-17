"""Painel único de saúde da inteligência (src.intelligence_dashboard, P5.2/P5.3).

Item 5.2 do PLANO_CEREBRO_ASSUME.md acrescenta `cycle_health`/`cycles`:
visibilidade de ciclo noturno TRAVADO (sem rodar há N dias), não só o
resultado agregado de quando roda."""

from datetime import datetime, timedelta, timezone

from src.intelligence_dashboard import answer_corpus_progress, build_snapshot, cycle_health
from src.jsonl_history import append_entry
from src.nanollm.experiment_log import log_experiment


class _FakeDB:
    def __init__(self, coverage=None, diag=None, raise_coverage=False, raise_diag=False):
        self._coverage = coverage or {"overall": {"nano": 3, "teacher": 7, "total": 10, "pct": 30.0},
                                      "tasks": {}}
        self._diag = diag or {"com_1a_mensagem_valida": 5, "pares_de_reacoes_up": 2}
        self._raise_coverage = raise_coverage
        self._raise_diag = raise_diag

    def nano_coverage(self):
        if self._raise_coverage:
            raise RuntimeError("banco fora do ar")
        return self._coverage

    def diagnose_pair_sourcing(self):
        if self._raise_diag:
            raise RuntimeError("banco fora do ar")
        return self._diag


class _FakeNano:
    def __init__(self, info=None):
        self._info = info or {"available": True, "ready": True, "params_m": 3.39, "val_ppl": 158.0}

    def info(self):
        return self._info


def test_build_snapshot_agrega_coverage_e_status():
    snap = build_snapshot(db=_FakeDB(), nano_engine=_FakeNano())
    assert snap["coverage"]["overall"]["pct"] == 30.0
    assert snap["nano_status"]["val_ppl"] == 158.0


def test_build_snapshot_calcula_volume_contra_o_limiar(monkeypatch):
    monkeypatch.setenv("FLYWHEEL_MIN_PAIRS", "5")
    snap = build_snapshot(db=_FakeDB(diag={"com_1a_mensagem_valida": 3, "pares_de_reacoes_up": 1}))
    assert snap["volume"] == {"min_pairs": 5, "faltam_titulo": 2, "faltam_reacoes": 4}


def test_build_snapshot_sem_db_nem_nano_fica_none():
    snap = build_snapshot()
    assert snap["coverage"] is None
    assert snap["nano_status"] is None
    assert snap["volume"] is None


def test_build_snapshot_coverage_falha_nao_derruba_volume():
    db = _FakeDB(raise_coverage=True)
    snap = build_snapshot(db=db)
    assert snap["coverage"] is None
    assert snap["volume"] is not None  # o outro bloco do MESMO db ainda funciona


def test_build_snapshot_diag_falha_nao_derruba_coverage():
    db = _FakeDB(raise_diag=True)
    snap = build_snapshot(db=db)
    assert snap["volume"] is None
    assert snap["coverage"] is not None


def test_build_snapshot_le_tendencia_dos_3_historicos(tmp_path):
    be_path = tmp_path / "be.jsonl"
    q_path = tmp_path / "q.jsonl"
    rg_path = tmp_path / "rg.jsonl"
    append_entry(be_path, {"nano_win_rate": 40.0})
    append_entry(be_path, {"nano_win_rate": 55.0})
    append_entry(q_path, {"pass_rate": 80.0})
    append_entry(rg_path, {"hit_rate": 90.0})

    snap = build_snapshot(
        blind_eval_history_path=be_path, quality_history_path=q_path,
        recall_gate_history_path=rg_path,
    )
    assert snap["blind_eval"]["latest"]["nano_win_rate"] == 55.0
    assert len(snap["blind_eval"]["trend"]) == 2
    assert snap["quality"]["latest"]["pass_rate"] == 80.0
    assert snap["recall_gate"]["latest"]["hit_rate"] == 90.0


def test_build_snapshot_historico_ausente_fica_none(tmp_path):
    snap = build_snapshot(
        blind_eval_history_path=tmp_path / "nao_existe.jsonl",
        quality_history_path=tmp_path / "nao_existe2.jsonl",
        recall_gate_history_path=tmp_path / "nao_existe3.jsonl",
    )
    assert snap["blind_eval"] is None
    assert snap["quality"] is None
    assert snap["recall_gate"] is None


def test_build_snapshot_respeita_trend_points(tmp_path):
    path = tmp_path / "be.jsonl"
    for i in range(15):
        append_entry(path, {"nano_win_rate": i})
    snap = build_snapshot(blind_eval_history_path=path, trend_points=5)
    assert len(snap["blind_eval"]["trend"]) == 5
    assert snap["blind_eval"]["latest"]["nano_win_rate"] == 14


# ── cycle_health (item 5.2) ────────────────────────────────────────
def test_cycle_health_ciclo_nunca_rodou_fica_stale(tmp_path):
    health = cycle_health({"quality": str(tmp_path / "nao_existe.jsonl")})
    assert health["quality"] == {"last_run": None, "days_since": None, "stale": True}


def test_cycle_health_ciclo_recente_nao_fica_stale(tmp_path):
    path = tmp_path / "q.jsonl"
    append_entry(path, {"pass_rate": 80.0})
    health = cycle_health({"quality": str(path)}, stale_after_days=2)
    assert health["quality"]["stale"] is False
    assert health["quality"]["days_since"] < 1


def test_cycle_health_ciclo_velho_fica_stale(tmp_path):
    path = tmp_path / "q.jsonl"
    append_entry(path, {"pass_rate": 80.0})
    fake_now = datetime.now(timezone.utc) + timedelta(days=5)
    health = cycle_health({"quality": str(path)}, stale_after_days=2, now=fake_now)
    assert health["quality"]["stale"] is True
    assert health["quality"]["days_since"] > 4


def test_build_snapshot_expoe_cycles(tmp_path):
    q_path = tmp_path / "q.jsonl"
    rg_path = tmp_path / "rg.jsonl"
    append_entry(q_path, {"pass_rate": 80.0})
    snap = build_snapshot(quality_history_path=q_path, recall_gate_history_path=rg_path)
    assert snap["cycles"]["quality"]["stale"] is False
    assert snap["cycles"]["recall_gate"]["stale"] is True  # nunca rodou nesse tmp_path


# ── answer_corpus_progress (item 4, PLANO_FLYWHEEL_AUTOMATICO.md) ──────────
def test_answer_corpus_progress_sem_dataset_fica_none(tmp_path):
    assert answer_corpus_progress(dataset_meta_path=tmp_path / "nao_existe.json") is None


def test_answer_corpus_progress_primeira_medicao_sem_tentativa_anterior(tmp_path):
    import json
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"pairs": 300}), encoding="utf-8")
    hist = tmp_path / "hist.jsonl"
    progress = answer_corpus_progress(dataset_meta_path=meta, experiment_log_path=hist,
                                      min_growth_pairs=200)
    assert progress["pairs"] == 300
    assert progress["last_attempt_pairs"] == 0
    assert progress["grown_since_last_attempt"] == 300
    assert progress["pairs_until_next_attempt"] == 0  # já cresceu mais que o piso
    assert progress["attempts_so_far"] == 0


def test_answer_corpus_progress_calcula_faltam_pro_proximo_piso(tmp_path):
    import json
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"pairs": 350}), encoding="utf-8")
    hist = tmp_path / "hist.jsonl"
    log_experiment(hist, name="answer_auto", base_ckpt="x", dataset="y",
                   hyperparams={"dataset_pairs": 300}, result={})
    progress = answer_corpus_progress(dataset_meta_path=meta, experiment_log_path=hist,
                                      min_growth_pairs=200)
    assert progress["grown_since_last_attempt"] == 50   # 350-300
    assert progress["pairs_until_next_attempt"] == 150  # 200-50
    assert progress["attempts_so_far"] == 1


def test_build_snapshot_inclui_answer_corpus(tmp_path, monkeypatch):
    import json
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"pairs": 88}), encoding="utf-8")
    monkeypatch.setattr("src.intelligence_dashboard.answer_corpus_progress",
                        lambda **k: {"pairs": 88})
    snap = build_snapshot()
    assert snap["answer_corpus"] == {"pairs": 88}
