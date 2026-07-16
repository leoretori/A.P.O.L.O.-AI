"""Prova numérica do backprop manual do Apolo-Nano.

Compara os gradientes analíticos (GPT.backward) com derivadas por diferença
finita central em float64. Se qualquer camada (atenção, LayerNorm, GELU,
embeddings, cross-entropy...) tiver backward errado, esses testes quebram.
"""

import numpy as np
import pytest

from src.nanollm.layers import alibi_slopes, gelu, gelu_backward
from src.nanollm.model import GPT, GPTConfig


def _loss(model: GPT, x: np.ndarray, y: np.ndarray) -> float:
    _, loss = model.forward(x, y)
    model._probs = None
    model._targets = None
    return loss


@pytest.fixture(scope="module")
def setup():
    config = GPTConfig(
        vocab_size=17, block_size=8, n_layer=1, n_head=2, n_embd=8,
        dtype="float64", seed=7,
    )
    model = GPT(config)
    rng = np.random.default_rng(3)
    x = rng.integers(0, 17, (2, 6))
    y = rng.integers(0, 17, (2, 6))
    model.zero_grad()
    _, _ = model.forward(x, y)
    model.backward()
    analytic = {p.name: p.grad.copy() for p in model.params()}
    return model, x, y, analytic


def test_gradcheck_todos_os_params(setup):
    """Diferença finita central em entradas amostradas de CADA parâmetro."""
    model, x, y, analytic = setup
    h = 1e-5
    rng = np.random.default_rng(11)
    piores: list[tuple[str, float]] = []
    for p in model.params():
        flat = p.data.reshape(-1)
        gflat = analytic[p.name].reshape(-1)
        n_samples = min(5, flat.size)
        idxs = rng.choice(flat.size, size=n_samples, replace=False)
        for i in idxs:
            orig = flat[i]
            flat[i] = orig + h
            lp = _loss(model, x, y)
            flat[i] = orig - h
            lm = _loss(model, x, y)
            flat[i] = orig
            num = (lp - lm) / (2 * h)
            ana = gflat[i]
            rel = abs(num - ana) / max(abs(num), abs(ana), 1e-8)
            piores.append((f"{p.name}[{i}]", rel))
            assert rel < 1e-4, (
                f"gradiente errado em {p.name}[{i}]: numérico {num:.8g} vs "
                f"analítico {ana:.8g} (rel {rel:.2e})"
            )
    # sanidade: a checagem realmente cobriu todos os tensores do modelo
    nomes = {n.split("[")[0] for n, _ in piores}
    assert len(nomes) == len(model.params())


def test_grad_nao_nulo_em_camadas_chave(setup):
    """Backward que 'esquece' uma camada produziria grad zero silencioso."""
    _, _, _, analytic = setup
    for nome in ["wte.w", "wpe.w", "h0.attn.qkv.w", "h0.mlp.fc.w", "ln_f.g", "lm_head.w"]:
        assert np.abs(analytic[nome]).max() > 0, f"gradiente zerado em {nome}"


def test_gelu_backward_numerico():
    rng = np.random.default_rng(5)
    x = rng.normal(0, 2, 64)
    dy = rng.normal(0, 1, 64)
    h = 1e-6
    num = (gelu(x + h) - gelu(x - h)) / (2 * h) * dy
    ana = gelu_backward(x, dy)
    np.testing.assert_allclose(ana, num, rtol=1e-5, atol=1e-7)


def test_atencao_e_causal():
    """Mudar um token FUTURO não pode mudar logits do passado."""
    config = GPTConfig(vocab_size=17, block_size=8, n_layer=2, n_head=2,
                       n_embd=8, dtype="float64", seed=7)
    model = GPT(config)
    x1 = np.array([[1, 2, 3, 4, 5, 6]])
    x2 = x1.copy()
    x2[0, -1] = 9  # só o último token muda
    l1, _ = model.forward(x1)
    l2, _ = model.forward(x2)
    np.testing.assert_allclose(l1[0, :-1], l2[0, :-1], rtol=1e-12)
    assert not np.allclose(l1[0, -1], l2[0, -1])


def test_zero_grad(setup):
    model, x, y, _ = setup
    model.zero_grad()
    _, _ = model.forward(x, y)
    model.backward()
    model.zero_grad()
    assert all(np.abs(p.grad).max() == 0 for p in model.params())


def test_backward_sem_targets_falha():
    model = GPT(GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2, n_embd=8))
    model.forward(np.array([[1, 2, 3]]))
    with pytest.raises(RuntimeError):
        model.backward()


def test_alibi_slopes_decrescem_e_somam_a_faixa_padrao():
    s = alibi_slopes(8)
    assert len(s) == 8
    assert all(s[i] > s[i + 1] for i in range(len(s) - 1))  # estritamente decrescente
    assert s[0] == pytest.approx(2 ** (-1.0), rel=1e-9)     # cabeça 0: 2^(-8/8·1)


# ── ALiBi (P1.5): viés relativo sem parâmetro, backward tem que continuar correto ──
@pytest.fixture(scope="module")
def setup_alibi():
    config = GPTConfig(
        vocab_size=17, block_size=8, n_layer=1, n_head=2, n_embd=8,
        dtype="float64", seed=7, pos_encoding="alibi",
    )
    model = GPT(config)
    rng = np.random.default_rng(3)
    x = rng.integers(0, 17, (2, 6))
    y = rng.integers(0, 17, (2, 6))
    model.zero_grad()
    _, _ = model.forward(x, y)
    model.backward()
    analytic = {p.name: p.grad.copy() for p in model.params()}
    return model, x, y, analytic


def test_gradcheck_alibi_todos_os_params(setup_alibi):
    """Mesma prova numérica do backprop, agora no caminho ALiBi — o viés é
    constante (sem grad próprio), mas isso não pode quebrar o resto da cadeia."""
    model, x, y, analytic = setup_alibi
    h = 1e-5
    rng = np.random.default_rng(11)
    for p in model.params():
        flat = p.data.reshape(-1)
        gflat = analytic[p.name].reshape(-1)
        idxs = rng.choice(flat.size, size=min(5, flat.size), replace=False)
        for i in idxs:
            orig = flat[i]
            flat[i] = orig + h
            lp = _loss(model, x, y)
            flat[i] = orig - h
            lm = _loss(model, x, y)
            flat[i] = orig
            num = (lp - lm) / (2 * h)
            ana = gflat[i]
            rel = abs(num - ana) / max(abs(num), abs(ana), 1e-8)
            assert rel < 1e-4, f"gradiente errado em {p.name}[{i}] (alibi): rel {rel:.2e}"


def test_alibi_nao_tem_wpe():
    model = GPT(GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2,
                          n_embd=8, pos_encoding="alibi"))
    assert model.wpe is None
    assert all(not p.name.startswith("wpe") for p in model.params())


def test_pos_encoding_invalido_falha():
    with pytest.raises(AssertionError):
        GPT(GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2,
                      n_embd=8, pos_encoding="rope_ainda_nao_existe"))


def test_alibi_e_causal():
    """A mesma prova de causalidade do 'learned', agora com o viés relativo."""
    config = GPTConfig(vocab_size=17, block_size=8, n_layer=2, n_head=2,
                       n_embd=8, dtype="float64", seed=7, pos_encoding="alibi")
    model = GPT(config)
    x1 = np.array([[1, 2, 3, 4, 5, 6]])
    x2 = x1.copy()
    x2[0, -1] = 9
    l1, _ = model.forward(x1)
    l2, _ = model.forward(x2)
    np.testing.assert_allclose(l1[0, :-1], l2[0, :-1], rtol=1e-12)
    assert not np.allclose(l1[0, -1], l2[0, -1])


def test_alibi_extrapola_alem_do_block_size_de_treino():
    """O PONTO do ALiBi (P1.5): sem tabela de posição, o forward aceita uma
    sequência MAIOR que o block_size configurado — o 'learned' levantaria
    ValueError aqui. Não afirma qualidade (isso é medido à parte, sweep de
    ppl), só que o mecanismo não trava."""
    config = GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2,
                       n_embd=8, pos_encoding="alibi")
    model = GPT(config)
    x = np.random.default_rng(0).integers(0, 17, (1, 20))  # 20 > block_size=8
    logits, _ = model.forward(x)
    assert logits.shape == (1, 20, 17)
    assert np.isfinite(logits).all()

    baseline = GPT(GPTConfig(vocab_size=17, block_size=8, n_layer=1, n_head=2,
                             n_embd=8, pos_encoding="learned"))
    with pytest.raises(ValueError):
        baseline.forward(x)
