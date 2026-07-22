"""Weight tying (E15) e amostragem decente (E13) — as duas no `model.py`.

O tying é a única mudança do projeto que altera a MATEMÁTICA do backward (o
mesmo peso recebe gradiente de dois papéis), então aqui ele é provado contra
gradiente numérico, como todo o resto do motor.
"""
import numpy as np
import pytest

from src.nanollm.model import GPT, GPTConfig


def _cfg(**kw):
    base = dict(vocab_size=24, block_size=8, n_layer=1, n_head=2, n_embd=16,
                dtype="float64", seed=7)
    base.update(kw)
    return GPTConfig(**base)


# ── E15: weight tying ────────────────────────────────────────────────────
def test_tying_libera_um_quarto_dos_parametros_do_v1():
    """Config REAL do ckpt_v1 (vocab 4096, n_embd 192, 4 camadas): 3,39M → 2,61M
    params, ou seja **23% liberados** sem tirar nenhuma camada. (O documento de
    erros estimou ~31%; medido no checkpoint de verdade, são 23% — a matriz
    duplicada é 0,79M, não 1,05M, porque n_embd é 192 e não 256.)"""
    real = dict(vocab_size=4096, block_size=192, n_layer=4, n_head=4, n_embd=192,
                dtype="float32", seed=1337)
    solto = GPT(GPTConfig(**real))
    amarrado = GPT(GPTConfig(**real, tie_weights=True))
    economia = solto.num_params - amarrado.num_params
    assert economia == 4096 * 192                   # exatamente a matriz vocab×n_embd
    assert 0.20 < economia / solto.num_params < 0.26


def test_tying_compartilha_o_buffer_de_verdade():
    m = GPT(_cfg(tie_weights=True))
    m.wte.w.data[3, 5] = 1.234
    assert m.lm_head.w.data[5, 3] == 1.234          # é a MESMA memória, transposta
    assert len([p for p in m.params() if p.name == "lm_head.w"]) == 0  # 1 update só


def test_tying_gradiente_bate_com_o_numerico():
    """Prova de que somar o gradiente dos dois papéis está certo."""
    model = GPT(_cfg(tie_weights=True))
    rng = np.random.default_rng(3)
    x = rng.integers(0, 24, (2, 6))
    y = rng.integers(0, 24, (2, 6))

    model.zero_grad()
    model.forward(x, y)
    model.backward()
    g = model.wte.w.grad.copy()

    h = 1e-6
    for i, j in [(0, 0), (5, 3), (17, 11)]:
        orig = model.wte.w.data[i, j]
        model.wte.w.data[i, j] = orig + h
        _, lp = model.forward(x, y)
        model.wte.w.data[i, j] = orig - h
        _, lm = model.forward(x, y)
        model.wte.w.data[i, j] = orig
        num = (lp - lm) / (2 * h)
        assert abs(num - g[i, j]) / max(abs(num), abs(g[i, j]), 1e-12) < 1e-5


def test_tying_treina_e_baixa_a_loss():
    """Sanidade de ponta a ponta: com o gradiente somado, o modelo aprende."""
    from src.nanollm.data import get_batch
    from src.nanollm.optim import Adam

    model = GPT(_cfg(vocab_size=16, tie_weights=True))
    tokens = np.tile(np.arange(16, dtype=np.uint16), 60)
    optim = Adam(model.params(), lr=1e-2)
    rng = np.random.default_rng(0)
    _, antes = model.forward(*get_batch(tokens, 8, 4, np.random.default_rng(1)))
    for _ in range(60):
        x, y = get_batch(tokens, 8, 4, rng)
        model.zero_grad()
        model.forward(x, y)
        model.backward()
        optim.step()
    _, depois = model.forward(*get_batch(tokens, 8, 4, np.random.default_rng(1)))
    assert depois < antes / 2


def test_tying_roundtrip_no_disco(tmp_path):
    m = GPT(_cfg(tie_weights=True))
    m.wte.w.data[:] = np.random.default_rng(1).normal(size=m.wte.w.data.shape)
    m.save(tmp_path / "m.npz")

    with np.load(tmp_path / "m.npz") as z:
        assert "lm_head.w" not in z                 # não grava a matriz duplicada
    volta = GPT.load(tmp_path / "m.npz")
    assert volta.tie_weights is True
    np.testing.assert_allclose(volta.wte.w.data, m.wte.w.data)
    np.testing.assert_allclose(volta.lm_head.w.data, m.wte.w.data.T)


def test_checkpoint_antigo_nao_vira_amarrado_por_engano(tmp_path):
    """Checkpoint sem `tie_weights` na config (todos os que já existem) tem as
    DUAS matrizes treinadas — amarrá-las jogaria a cabeça fora, em silêncio."""
    import json

    solto = GPT(_cfg())
    solto.save(tmp_path / "antigo.npz")
    # simula o formato anterior ao E15: config sem a chave
    with np.load(tmp_path / "antigo.npz") as z:
        arrays = {k: z[k] for k in z.files}
    cfg = json.loads(bytes(arrays["__config__"]).decode("utf-8"))
    cfg.pop("tie_weights", None)
    arrays["__config__"] = np.frombuffer(json.dumps(cfg).encode("utf-8"), dtype=np.uint8)
    np.savez_compressed(tmp_path / "antigo.npz", **arrays)

    volta = GPT.load(tmp_path / "antigo.npz")
    assert volta.tie_weights is False
    np.testing.assert_allclose(volta.lm_head.w.data, solto.lm_head.w.data)


# ── E13: amostragem ──────────────────────────────────────────────────────
def _logits(vals):
    return np.array([vals], dtype=np.float64)


def test_repeat_penalty_derruba_token_ja_gerado():
    rng = np.random.default_rng(0)
    logits = _logits([5.0, 4.0, 0.0, 0.0])
    sem = GPT._sample(logits, 1.0, 0, rng, np.int64)[0, 0]
    assert sem == 0                                   # greedy-ish: o maior vence

    com = GPT._sample(logits, 0.01, 0, rng, np.int64, repeat_penalty=2.0,
                      recent=np.array([[0]]))[0, 0]
    assert com == 1                                   # o 0 foi penalizado


def test_repeat_penalty_tambem_penaliza_logit_negativo():
    """Dividir um logit negativo o AUMENTARIA — tem que multiplicar."""
    rng = np.random.default_rng(0)
    logits = _logits([-1.0, -2.0])
    escolha = GPT._sample(logits, 0.01, 0, rng, np.int64, repeat_penalty=4.0,
                          recent=np.array([[0]]))[0, 0]
    assert escolha == 1                               # -1 virou -4, perdeu p/ -2


def test_top_p_corta_a_cauda():
    rng = np.random.default_rng(0)
    logits = _logits([10.0, 9.9, -20.0, -20.0])
    saidas = {int(GPT._sample(logits, 1.0, 0, rng, np.int64, top_p=0.9)[0, 0])
              for _ in range(50)}
    assert saidas <= {0, 1}                           # a cauda nunca é sorteada


def test_top_p_nunca_zera_a_distribuicao():
    """Mesmo com um token dominante, o nucleus tem que manter pelo menos ele."""
    rng = np.random.default_rng(0)
    logits = _logits([50.0, 0.0, 0.0])
    assert int(GPT._sample(logits, 1.0, 0, rng, np.int64, top_p=0.5)[0, 0]) == 0


def test_penalidade_nao_atinge_os_tokens_do_prompt():
    """As tarefas do Nano completam um padrão REUSANDO palavras do prompt
    (`title_relevant` exige isso) — penalizar o prompt sabotava a relevância,
    medido no checkpoint vivo."""
    model = GPT(GPTConfig(vocab_size=16, block_size=16, n_layer=1, n_head=2,
                          n_embd=16, seed=1))
    prompt = np.array([[3, 3, 3, 3]], dtype=np.int64)
    saida = model.generate_fast(prompt, 6, top_k=1, rng=np.random.default_rng(0),
                                repeat_penalty=1000.0)
    # com penalidade absurda, o 1º token gerado ainda pode ser o 3 (veio do
    # prompt, não da geração); o que não pode é o 3 se repetir DEPOIS de gerado
    gerados = [int(t) for t in saida[0, 4:]]
    assert len(gerados) == 6
    assert gerados.count(gerados[0]) == 1


def test_sem_penalidade_o_comportamento_e_o_de_antes():
    """Padrões neutros (1.0 / 0.0) têm que reproduzir a amostragem original."""
    model = GPT(GPTConfig(vocab_size=32, block_size=16, n_layer=1, n_head=2,
                          n_embd=16, seed=2))
    p = np.array([[1, 2, 3]], dtype=np.int64)
    a = model.generate_fast(p, 10, temperature=0.9, rng=np.random.default_rng(4))
    b = model.generate_fast(p, 10, temperature=0.9, rng=np.random.default_rng(4),
                            repeat_penalty=1.0, top_p=0.0)
    np.testing.assert_array_equal(a, b)


@pytest.mark.parametrize("texto,stop,esperado,qual", [
    ("resposta boa\n\nPergunta: outra", ["Pergunta:"], "resposta boa\n\n", "Pergunta:"),
    ("sem parada aqui", ["Pergunta:"], "sem parada aqui", None),
    ("aX bY", ["bY", "X"], "a", "X"),               # pega a stop mais à esquerda
    ("qualquer", None, "qualquer", None),
])
def test_cut_at_stop(texto, stop, esperado, qual):
    from src.nanollm.engine import _cut_at_stop
    assert _cut_at_stop(texto, stop) == (esperado, qual)
