"""Treino, checkpoint, otimizador e geração do Apolo-Nano."""

import numpy as np
import pytest

from src.nanollm.data import get_batch
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.optim import Adam, clip_grad_norm, lr_schedule


def _tiny_model(seed: int = 1) -> GPT:
    return GPT(GPTConfig(vocab_size=16, block_size=16, n_layer=1, n_head=2,
                         n_embd=32, seed=seed))


def test_overfit_sequencia_simples():
    """O modelo TEM que decorar um padrão determinístico — senão o treino
    inteiro (loss/backward/Adam) está quebrado."""
    model = _tiny_model()
    tokens = np.tile(np.arange(16, dtype=np.uint16), 64)  # 0,1,...,15,0,1,...
    optim = Adam(model.params(), lr=1e-2)
    rng = np.random.default_rng(0)

    first_loss = None
    loss = None
    for step in range(120):
        x, y = get_batch(tokens, model.config.block_size, 8, rng)
        model.zero_grad()
        _, loss = model.forward(x, y)
        model.backward()
        clip_grad_norm(model.params(), 1.0)
        optim.step()
        if first_loss is None:
            first_loss = loss
    assert first_loss > 2.0  # começa perto de ln(16) ≈ 2.77
    assert loss < 0.5, f"não aprendeu: loss final {loss:.3f}"


def test_checkpoint_roundtrip(tmp_path):
    model = _tiny_model()
    path = tmp_path / "model.npz"
    model.save(path)
    clone = GPT.load(path)
    assert clone.config == model.config
    x = np.array([[1, 2, 3, 4]])
    l1, _ = model.forward(x)
    l2, _ = clone.forward(x)
    np.testing.assert_array_equal(l1, l2)


def test_adam_state_roundtrip(tmp_path):
    model = _tiny_model()
    optim = Adam(model.params(), lr=1e-3)
    x = np.array([[1, 2, 3]])
    y = np.array([[2, 3, 4]])
    model.zero_grad()
    model.forward(x, y)
    model.backward()
    optim.step()
    path = tmp_path / "optim.npz"
    optim.save(path)

    optim2 = Adam(_tiny_model().params(), lr=1e-3)
    optim2.load(path)
    assert optim2.t == optim.t == 1
    for name in optim.m:
        np.testing.assert_array_equal(optim2.m[name], optim.m[name])
        np.testing.assert_array_equal(optim2.v[name], optim.v[name])


def test_generate_shape_e_vocab():
    model = _tiny_model()
    idx = np.array([[1, 2, 3]], dtype=np.int64)
    out = model.generate(idx, max_new_tokens=10, rng=np.random.default_rng(0))
    assert out.shape == (1, 13)
    np.testing.assert_array_equal(out[:, :3], idx)  # prompt preservado
    assert int(out.max()) < model.config.vocab_size
    assert int(out.min()) >= 0


def test_generate_para_no_stop_id():
    model = _tiny_model()
    idx = np.array([[1]], dtype=np.int64)
    # top_k=1 + temperatura mínima → determinístico; com stop_id igual a TODO
    # o vocabulário impossível, gera os N tokens completos
    out = model.generate(idx, max_new_tokens=5, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] == 6


def test_generate_respeita_contexto_maximo():
    model = _tiny_model()
    idx = np.ones((1, 16), dtype=np.int64)  # já no block_size
    out = model.generate(idx, max_new_tokens=3, rng=np.random.default_rng(0))
    assert out.shape == (1, 19)  # não estoura, faz janela deslizante


def test_lr_schedule():
    kw = dict(max_lr=1e-3, min_lr=1e-4, warmup=10, total=100)
    assert lr_schedule(0, **kw) == pytest.approx(1e-4)
    assert lr_schedule(9, **kw) == pytest.approx(1e-3)
    assert lr_schedule(10, **kw) == pytest.approx(1e-3)
    meio = lr_schedule(55, **kw)
    assert 1e-4 < meio < 1e-3
    assert lr_schedule(100, **kw) == pytest.approx(1e-4)
    assert lr_schedule(500, **kw) == pytest.approx(1e-4)


def test_clip_grad_norm():
    model = _tiny_model()
    for p in model.params():
        p.grad[...] = 1.0
    norm_antes = clip_grad_norm(model.params(), max_norm=1.0)
    assert norm_antes > 1.0
    norm_depois = clip_grad_norm(model.params(), max_norm=1e9)
    assert norm_depois == pytest.approx(1.0, rel=1e-6)


def test_num_params_e_seed_reprodutivel():
    a, b = _tiny_model(seed=5), _tiny_model(seed=5)
    assert a.num_params == b.num_params > 0
    np.testing.assert_array_equal(a.wte.w.data, b.wte.w.data)
    c = _tiny_model(seed=6)
    assert not np.array_equal(a.wte.w.data, c.wte.w.data)


def test_sequencia_maior_que_contexto_falha():
    model = _tiny_model()
    with pytest.raises(ValueError):
        model.forward(np.ones((1, 17), dtype=np.int64))


def test_finetune_init_from_warm_start(tmp_path):
    """--init-from carrega os pesos de outro ckpt mas começa run NOVO."""
    import argparse
    import json as _json

    from src.nanollm.train import PRESETS, train

    # checkpoint de origem (pesos "pré-treinados")
    src = tmp_path / "base"
    src.mkdir()
    base = _tiny_model(seed=3)
    base.save(src / "model_best.npz")
    (src / "tokenizer.json").write_text('{"version":1,"type":"byte-bpe","merges":[],'
                                        '"special":{"<|sep|>":256}}', encoding="utf-8")
    w0 = base.wte.w.data.copy()

    # dataset de tarefa mínimo (vocab tem que bater com o do modelo base)
    data = tmp_path / "data"
    data.mkdir()
    rng = np.random.default_rng(0)
    np.save(data / "train.npy", rng.integers(0, 16, 500).astype(np.uint16))
    np.save(data / "val.npy", rng.integers(0, 16, 120).astype(np.uint16))
    (data / "meta.json").write_text(_json.dumps({"vocab_size": 16}), encoding="utf-8")

    out = tmp_path / "ft"
    args = argparse.Namespace(
        data=str(data), out=str(out), preset="nano", steps=3, batch_size=4,
        lr=1e-3, warmup=1, weight_decay=0.0, grad_clip=1.0, log_every=10,
        eval_every=3, eval_iters=2, seed=1, resume=False, init_from=str(src),
    )
    # o modelo base é n_embd=32 (não o preset nano) → veio do checkpoint, não do preset
    result = train(args)
    assert result["step"] == 3
    assert (out / "tokenizer.json").exists()  # tokenizer herdado da origem
    trained = GPT.load(out / "model.npz")
    assert trained.config.n_embd == 32  # config veio dos PESOS, não do preset nano(128)
    assert not np.array_equal(trained.wte.w.data, w0)  # treinou (pesos mudaram)
    assert PRESETS["nano"]["n_embd"] == 128  # sanidade: o preset seria outro
