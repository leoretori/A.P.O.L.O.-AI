"""Painel único de saúde da inteligência (src.intelligence_dashboard, P5.2/P5.3)."""

from src.intelligence_dashboard import build_snapshot
from src.jsonl_history import append_entry


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
