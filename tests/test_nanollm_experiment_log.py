"""Histórico de experimentos de fine-tune (src.nanollm.experiment_log, item 3
do PLANO_CORPUS_DIVERSO.md)."""

from src.nanollm.experiment_log import log_experiment, read_experiment_history


def test_log_experiment_grava_e_le(tmp_path):
    path = tmp_path / "hist.jsonl"
    entry = log_experiment(
        path, name="answer_v1", base_ckpt="ckpt_v1",
        dataset="data/nano/distill_answers (346 pares)",
        hyperparams={"lr": 6e-4, "steps": 2000, "patience": 5, "stopped_at": 350},
        result={"blind_eval_win_rate": 20.0, "baseline_win_rate": 33.3, "promoted": False},
        notes="piorou o baseline - dataset topicamente estreito",
    )
    assert entry["name"] == "answer_v1"
    assert entry["result"]["promoted"] is False

    hist = read_experiment_history(path)
    assert len(hist) == 1
    assert hist[0]["name"] == "answer_v1"
    assert hist[0]["hyperparams"]["patience"] == 5
    assert "timestamp" in hist[0]  # carimbo automático do jsonl_history


def test_log_experiment_acumula_historico_sem_reescrever(tmp_path):
    path = tmp_path / "hist.jsonl"
    log_experiment(path, name="title_4.2", base_ckpt="ckpt_v1", dataset="201 pares",
                   hyperparams={"lr": 2e-4}, result={"gate_pass_rate": 1 / 6})
    log_experiment(path, name="answer_v1", base_ckpt="ckpt_v1", dataset="346 pares",
                   hyperparams={"lr": 6e-4}, result={"blind_eval_win_rate": 20.0})
    hist = read_experiment_history(path)
    assert len(hist) == 2
    assert [h["name"] for h in hist] == ["title_4.2", "answer_v1"]


def test_read_experiment_history_arquivo_inexistente(tmp_path):
    assert read_experiment_history(tmp_path / "nao_existe.jsonl") == []
