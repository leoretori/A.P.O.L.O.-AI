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


def test_janela_desliza_em_vez_de_parar():
    """E2: encher o contexto NÃO para mais a geração — a janela desliza
    (re-prefill com a metade recente) e os N tokens pedidos saem."""
    model = _model(block=16)
    prompt = np.ones((1, 10), dtype=np.int64)
    out = model.generate_fast(prompt, 100, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] == 10 + 100


def test_prompt_maior_que_contexto_devolve_o_prompt_inteiro():
    """E2: a janela recorta o prompt para o modelo, mas o array devolvido
    mantém o prompt ORIGINAL — senão `out[0, len(ids):]` do chamador dá vazio."""
    model = _model(block=16)
    prompt = np.arange(40, dtype=np.int64)[None, :] % 64
    out = model.generate_fast(prompt, 5, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] == 40 + 5
    np.testing.assert_array_equal(out[:, :40], prompt)      # prompt preservado
    assert len(out[0, 40:]) == 5                            # e 5 tokens NOVOS


def test_prompt_longo_nao_gera_texto_vazio():
    """O modo de falha real do E2, no formato do chamador (engine/generate)."""
    model = _model(block=16)
    ids = list(np.arange(200) % 64)
    out = model.generate_fast(np.array([ids], dtype=np.int64), 20, top_k=1,
                              rng=np.random.default_rng(0))
    novos = [int(t) for t in out[0, len(ids):]]
    assert len(novos) == 20


def test_prompt_tokens_used_reporta_a_truncagem():
    model = _model(block=16)
    assert model.prompt_tokens_used(5) == 5            # coube inteiro
    assert model.prompt_tokens_used(200) == 15         # block_size - 1


def test_alibi_gera_alem_do_block_size_no_caminho_rapido():
    """E11: com ALiBi o viés é relativo — o cache pode passar do block_size de
    treino (o caminho lento já fazia isso; o rápido truncava igual ao learned)."""
    model = GPT(GPTConfig(vocab_size=64, block_size=16, n_layer=2, n_head=2,
                          n_embd=32, seed=9, pos_encoding="alibi"))
    assert model.context_limit() > model.config.block_size
    prompt = np.ones((1, 4), dtype=np.int64)
    out = model.generate_fast(prompt, 40, top_k=1, rng=np.random.default_rng(0))
    assert out.shape[1] == 44          # 44 > block_size 16, sem re-prefill


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
