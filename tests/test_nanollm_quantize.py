"""Quantização int8 de checkpoint (M5.2 do roadmap do Nano): checkpoint menor
p/ inferência, com degradação de qualidade medida (não presumida)."""
import numpy as np

from src.nanollm.eval import perplexity
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.quantize import dequantize_int8, quantize_int8


def test_quantize_dequantize_erro_pequeno():
    rng = np.random.default_rng(0)
    w = rng.normal(0.0, 0.02, (48, 32)).astype("float32")
    q, scale = quantize_int8(w)
    assert q.dtype == np.int8
    assert scale.shape == (32,)
    w2 = dequantize_int8(q, scale)
    # erro máximo dentro de ~1 nível de quantização por coluna (amax/127)
    tol = (np.abs(w).max(axis=0) / 127) * 1.01
    assert np.all(np.abs(w2 - w).max(axis=0) <= tol + 1e-8)


def test_quantize_coluna_nula_nao_gera_nan_ou_divisao_por_zero():
    w = np.zeros((8, 4), dtype="float32")
    q, scale = quantize_int8(w)
    w2 = dequantize_int8(q, scale)
    assert np.all(w2 == 0) and not np.any(np.isnan(w2))


def _small_model(seed=1):
    cfg = GPTConfig(vocab_size=200, block_size=32, n_layer=2, n_head=2, n_embd=32, seed=seed)
    return GPT(cfg)


def test_save_quantized_e_load_preserva_comportamento_de_perto(tmp_path):
    model = _small_model()
    idx = np.array([[3, 5, 7, 9, 11]])
    logits1, _ = model.forward(idx)

    path = tmp_path / "q.npz"
    info = model.save_quantized(path)
    assert info["quantized"] > 0

    model2 = GPT.load(path)  # load() dequantiza sozinho — transparente
    logits2, _ = model2.forward(idx)
    # não é bit-idêntico (int8 introduz ruído), mas deve estar bem correlacionado
    corr = np.corrcoef(logits1.flatten(), logits2.flatten())[0, 1]
    assert corr > 0.97


def test_checkpoint_quantizado_e_bem_menor_no_disco(tmp_path):
    model = _small_model()
    p_full = tmp_path / "full.npz"
    p_q = tmp_path / "q.npz"
    model.save(p_full)
    model.save_quantized(p_q)
    assert p_q.stat().st_size < p_full.stat().st_size * 0.6


def test_degradacao_de_perplexity_abaixo_de_2_por_cento(tmp_path):
    """DoD do M5.2: degradação de ppl < 2% no round-trip de quantização."""
    model = _small_model()
    # alguns passos de treino p/ os pesos saírem do puro ruído de inicialização
    rng = np.random.default_rng(7)
    tokens = rng.integers(0, model.config.vocab_size, size=4000).astype(np.int64)
    from src.nanollm.data import get_batch
    from src.nanollm.optim import Adam
    optim = Adam(model.params(), lr=3e-3)
    for _ in range(20):
        x, y = get_batch(tokens, model.config.block_size, 8, rng)
        model.zero_grad()
        model.forward(x, y)
        model.backward()
        optim.step(3e-3)

    ppl_before = perplexity(model, tokens, batch_size=4)["ppl"]

    path = tmp_path / "q.npz"
    model.save_quantized(path)
    model_q = GPT.load(path)
    ppl_after = perplexity(model_q, tokens, batch_size=4)["ppl"]

    degradation = (ppl_after - ppl_before) / ppl_before
    assert degradation < 0.02, f"ppl {ppl_before} -> {ppl_after} ({degradation:.1%})"
