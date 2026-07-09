"""KV cache (Épico 3.1): geração incremental equivalente ao caminho lento."""

import numpy as np

from src.nanollm.model import GPT, GPTConfig


def _model(block: int = 32) -> GPT:
    return GPT(GPTConfig(vocab_size=64, block_size=block, n_layer=2, n_head=2,
                         n_embd=32, seed=9))


def test_logits_do_step_equivalem_ao_forward_completo():
    """Prefill+steps tem que reproduzir os logits do forward cheio."""
    model = _model()
    rng = np.random.default_rng(1)
    seq = rng.integers(0, 64, (2, 10))

    full, _ = model.forward(seq)  # (2, 10, V)

    logits = model._prefill(seq[:, :4])
    np.testing.assert_allclose(logits, full[:, :4], rtol=1e-5, atol=1e-6)
    for pos in range(4, 10):
        step = model._step(seq[:, pos : pos + 1], pos=pos)
        np.testing.assert_allclose(step[:, 0], full[:, pos], rtol=1e-5, atol=1e-6)


def test_greedy_identico_nos_dois_caminhos():
    """top_k=1 (determinístico): fast e slow geram exatamente os mesmos tokens."""
    model = _model()
    prompt = np.array([[3, 14, 15]], dtype=np.int64)
    slow = model.generate(prompt, 20, top_k=1, rng=np.random.default_rng(0))
    fast = model.generate_fast(prompt, 20, top_k=1, rng=np.random.default_rng(0))
    np.testing.assert_array_equal(slow, fast)


def test_amostragem_mesma_seed_mesmos_tokens():
    model = _model()
    prompt = np.array([[7, 7, 7]], dtype=np.int64)
    a = model.generate_fast(prompt, 15, temperature=0.9, rng=np.random.default_rng(5))
    b = model.generate_fast(prompt, 15, temperature=0.9, rng=np.random.default_rng(5))
    np.testing.assert_array_equal(a, b)  # cache é resetado a cada chamada


def test_para_ao_encher_o_contexto():
    model = _model(block=16)
    prompt = np.ones((1, 10), dtype=np.int64)
    out = model.generate_fast(prompt, 100, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] == 16  # parou no block_size, sem estourar


def test_prompt_maior_que_contexto_e_recortado():
    model = _model(block=16)
    prompt = np.arange(40, dtype=np.int64)[None, :] % 64
    out = model.generate_fast(prompt, 5, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] <= 16 + 5  # recorta p/ caber e segue


def test_stop_id_respeitado_no_fast():
    model = _model()
    prompt = np.array([[1, 2]], dtype=np.int64)
    # greedy: descobre o 1º token gerado e usa ele como stop
    first = model.generate_fast(prompt, 1, top_k=1, rng=np.random.default_rng(0))
    stop = int(first[0, -1])
    out = model.generate_fast(prompt, 30, top_k=1, rng=np.random.default_rng(0),
                              stop_id=stop)
    assert out.shape[1] == 3  # parou imediatamente no stop_id
    assert int(out[0, -1]) == stop


def test_kv_len_cresce_por_camada():
    model = _model()
    model._prefill(np.array([[1, 2, 3]], dtype=np.int64))
    assert all(b.attn.kv_len == 3 for b in model.blocks)
    model._step(np.array([[4]], dtype=np.int64), pos=3)
    assert all(b.attn.kv_len == 4 for b in model.blocks)


def test_gradcheck_continua_verde_apos_kv():
    """O caminho de TREINO não pode ter sido tocado pelo cache: forward com
    keep_kv default False + backward seguem batendo com o gradiente numérico."""
    model = GPT(GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2,
                          n_embd=8, dtype="float64", seed=7))
    rng = np.random.default_rng(3)
    x = rng.integers(0, 17, (2, 6))
    y = rng.integers(0, 17, (2, 6))
    model.zero_grad()
    model.forward(x, y)
    model.backward()
    p = model.blocks[0].attn.qkv.w
    h = 1e-5
    flat = p.data.reshape(-1)
    g = p.grad.reshape(-1)
    i = 5
    orig = flat[i]
    flat[i] = orig + h
    _, lp = model.forward(x, y)
    flat[i] = orig - h
    _, lm = model.forward(x, y)
    flat[i] = orig
    num = (lp - lm) / (2 * h)
    assert abs(num - g[i]) / max(abs(num), abs(g[i])) < 1e-4
