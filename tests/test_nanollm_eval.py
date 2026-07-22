"""Harness de avaliação (src/nanollm/eval): perplexity fixa + sondas + relatório."""

import json

import numpy as np
import pytest

from src.nanollm.eval import PROBES_V1, evaluate, perplexity, run_probes
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.optim import Adam
from src.nanollm.tokenizer import ByteBPETokenizer


def _tiny_model(vocab: int = 300) -> GPT:
    return GPT(GPTConfig(vocab_size=vocab, block_size=16, n_layer=1, n_head=2,
                         n_embd=32, seed=1))


@pytest.fixture()
def ckpt(tmp_path):
    """Checkpoint completo (modelo + tokenizer + state) + dataset val."""
    tok = ByteBPETokenizer()
    tok.train("O Apolo aprende sozinho todos os dias. " * 40, vocab_size=300)
    model = _tiny_model(vocab=tok.vocab_size)
    ck = tmp_path / "ckpt"
    ck.mkdir()
    model.save(ck / "model.npz")
    tok.save(ck / "tokenizer.json")
    (ck / "state.json").write_text(json.dumps({"step": 42, "best_val": 5.0}))
    data = tmp_path / "data"
    data.mkdir()
    rng = np.random.default_rng(0)
    np.save(data / "val.npy", rng.integers(0, tok.vocab_size, 600).astype(np.uint16))
    return model, tok, ck, data


def test_ppl_modelo_virgem_perto_do_vocab(ckpt):
    """Sem treino, a ppl tem que ficar na ordem do tamanho do vocabulário."""
    model, _, _, data = ckpt
    val = np.load(data / "val.npy")
    r = perplexity(model, val)
    assert 0.5 * model.config.vocab_size < r["ppl"] < 2.0 * model.config.vocab_size
    assert r["windows"] > 0 and r["tokens_avaliados"] > 0


def test_ppl_deterministica(ckpt):
    model, _, _, data = ckpt
    val = np.load(data / "val.npy")
    assert perplexity(model, val) == perplexity(model, val)


def test_ppl_cai_com_treino():
    """Treinar em padrão fixo TEM que baixar a ppl medida no mesmo padrão."""
    model = _tiny_model(vocab=16)
    tokens = np.tile(np.arange(16, dtype=np.uint16), 80)
    antes = perplexity(model, tokens)["ppl"]
    optim = Adam(model.params(), lr=1e-2)
    rng = np.random.default_rng(0)
    from src.nanollm.data import get_batch
    for _ in range(60):
        x, y = get_batch(tokens, 16, 8, rng)
        model.zero_grad()
        model.forward(x, y)
        model.backward()
        optim.step()
    depois = perplexity(model, tokens)["ppl"]
    assert depois < antes / 3


def test_ppl_val_pequeno_demais_falha():
    """Val curto encolhe a janela (E1b) — mas 2 tokens não dão nem x/y."""
    model = _tiny_model()
    with pytest.raises(ValueError):
        perplexity(model, np.zeros(2, dtype=np.uint16))


def test_ppl_val_curto_encolhe_a_janela(ckpt):
    """Menos que uma janela cheia mede assim mesmo, e REPORTA o block usado."""
    model, _, _, _ = ckpt
    r = perplexity(model, np.zeros(10, dtype=np.uint16))
    assert r["windows"] >= 1 and r["block"] == 8 < model.config.block_size


def test_sondas_deterministicas(ckpt):
    model, tok, _, _ = ckpt
    a = run_probes(model, tok, n_tokens=8)
    b = run_probes(model, tok, n_tokens=8)
    assert a == b  # mesma seed fixa → mesmas saídas
    assert len(a) == len(PROBES_V1) == 10
    assert all(s["prompt"] and isinstance(s["texto"], str) for s in a)


def test_evaluate_relatorio_e_historico(ckpt):
    model, _, ck, data = ckpt
    r1 = evaluate(ck, data, probes=False)
    r2 = evaluate(ck, data, probes=False)
    assert r1["passo_treino"] == 42
    assert r1["val"]["ppl"] == r2["val"]["ppl"]  # comparável entre runs
    assert r1["params_m"] > 0
    report = json.loads((ck / "eval_report.json").read_text(encoding="utf-8"))
    assert report["val"]["ppl"] == r2["val"]["ppl"]
    linhas = (ck / "evals.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(linhas) == 2  # histórico acumula 1 linha por run
    assert json.loads(linhas[0])["val"]["ppl"] == r1["val"]["ppl"]


def test_evaluate_com_sondas(ckpt):
    _, _, ck, data = ckpt
    r = evaluate(ck, data)
    assert len(r["sondas"]) == 10
    assert r["probes_version"] == "v1"
