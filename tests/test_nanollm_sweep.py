"""Sweep de scaling-law compute-matched (src/nanollm/sweep, P1.2 do PLANO_7_PILARES)."""

import json

import numpy as np
import pytest

from src.nanollm.sweep import _preset_params, run_sweep, steps_for_budget
from src.nanollm.train import PRESETS


def test_preset_params_cresce_com_o_tamanho():
    """A base de tudo: contar parâmetros sem treinar tem que bater a ordem dos presets."""
    counts = [_preset_params(name, vocab_size=4096)
              for name in ("nano", "mini", "small", "medium", "large")]
    assert counts == sorted(counts) and len(set(counts)) == len(counts)


def test_steps_for_budget_proporcional_a_params():
    """O CERNE da correção do bug do M6.1: preset com mais params deve receber
    MAIS passos (não o mesmo número fixo) para o mesmo orçamento tokens/param."""
    p_nano = _preset_params("nano", 4096)
    p_medium = _preset_params("medium", 4096)
    steps_nano = steps_for_budget(p_nano, PRESETS["nano"]["batch_size"],
                                  PRESETS["nano"]["block_size"], tokens_per_param=15.0)
    steps_medium = steps_for_budget(p_medium, PRESETS["medium"]["batch_size"],
                                    PRESETS["medium"]["block_size"], tokens_per_param=15.0)
    tokens_nano = steps_nano * PRESETS["nano"]["batch_size"] * PRESETS["nano"]["block_size"]
    tokens_medium = steps_medium * PRESETS["medium"]["batch_size"] * PRESETS["medium"]["block_size"]
    # medium tem ~12x mais params que nano → tem que ver proporcionalmente mais tokens
    assert tokens_medium > tokens_nano
    assert tokens_medium / p_medium == pytest.approx(tokens_nano / p_nano, rel=0.15)


def test_steps_for_budget_respeita_o_minimo():
    assert steps_for_budget(params=100, batch_size=16, block_size=128,
                            tokens_per_param=0.001, min_steps=20) == 20


@pytest.fixture()
def dataset(tmp_path):
    """Dataset sintético mas real o bastante p/ treinar de verdade (não mock de train())."""
    rng = np.random.default_rng(0)
    vocab = 64
    data = tmp_path / "data"
    data.mkdir()
    np.save(data / "train.npy", rng.integers(0, vocab, 4000).astype(np.uint16))
    np.save(data / "val.npy", rng.integers(0, vocab, 500).astype(np.uint16))
    (data / "meta.json").write_text(json.dumps({"vocab_size": vocab, "tokens": 4500}),
                                    encoding="utf-8")
    return data


def test_run_sweep_produz_tabela_com_3_pontos(dataset, tmp_path, monkeypatch):
    # presets pequenos o bastante p/ caber no vocab/tokens sintéticos e rodar rápido
    monkeypatch.setitem(PRESETS, "nano", dict(n_layer=1, n_head=2, n_embd=16,
                                              block_size=16, batch_size=8))
    monkeypatch.setitem(PRESETS, "mini", dict(n_layer=1, n_head=2, n_embd=24,
                                              block_size=16, batch_size=8))
    monkeypatch.setitem(PRESETS, "small", dict(n_layer=2, n_head=2, n_embd=32,
                                               block_size=16, batch_size=8))
    out = tmp_path / "sweep"
    report = run_sweep(dataset, out, ["nano", "mini", "small"],
                       tokens_per_param=0.01, eval_iters=2, verbose=False)

    assert len(report["rows"]) == 3
    names = [r["preset"] for r in report["rows"]]
    assert names == ["nano", "mini", "small"]
    params = [r["params"] for r in report["rows"]]
    assert params == sorted(params) and len(set(params)) == 3  # cresce e não empata
    for r in report["rows"]:
        assert r["steps"] >= 20  # o mínimo do orçamento minúsculo do teste
        assert r["val_loss"] > 0
        assert r["ppl"] > 0
        assert (out / r["preset"] / "model.npz").exists()
    assert json.loads((out / "sweep_report.json").read_text(encoding="utf-8")) == report


def test_run_sweep_determinismo(dataset, tmp_path, monkeypatch):
    monkeypatch.setitem(PRESETS, "nano", dict(n_layer=1, n_head=2, n_embd=16,
                                              block_size=16, batch_size=8))
    r1 = run_sweep(dataset, tmp_path / "a", ["nano"], tokens_per_param=0.01,
                   eval_iters=2, seed=7, verbose=False)
    r2 = run_sweep(dataset, tmp_path / "b", ["nano"], tokens_per_param=0.01,
                   eval_iters=2, seed=7, verbose=False)
    assert r1["rows"][0]["val_loss"] == r2["rows"][0]["val_loss"]
