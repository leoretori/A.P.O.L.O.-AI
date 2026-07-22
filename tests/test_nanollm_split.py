"""Split de validação por documento (E14), janela do get_batch (E27) e
decode que avisa (E25) — a base de dados do treino.

Sem isto, `best_val`/early-stop otimizavam contra um val enviesado: a cauda
do último arquivo em ordem alfabética, ou seja, UMA fonte só.
"""
import json

import numpy as np
import pytest

from src.nanollm.data import _pick_val_docs, _sample_docs, build_dataset, get_batch


def _corpus(tmp_path, n_docs=12, marcador="doc"):
    """Um .txt por documento, com conteúdo DISTINGUÍVEL por documento."""
    d = tmp_path / "corpus"
    d.mkdir()
    for i in range(n_docs):
        (d / f"{i:02d}.txt").write_text(
            f"{marcador}{i} " + f"assunto do documento numero {i}. " * 30,
            encoding="utf-8")
    return d


def test_val_nao_e_a_cauda_do_ultimo_arquivo(tmp_path):
    """E14: com split por documento, o val NÃO é o fim do último arquivo."""
    corpus = _corpus(tmp_path)
    meta = build_dataset(corpus, tmp_path / "out", vocab_size=300,
                         val_fraction=0.2, verbose=False, seed=7)
    assert meta["val_docs"] >= 1
    assert "por documento" in meta["split"]
    assert meta["train_tokens"] + meta["val_tokens"] == meta["tokens"]

    from src.nanollm.tokenizer import ByteBPETokenizer
    tok = ByteBPETokenizer.load(tmp_path / "out" / "tokenizer.json")
    val = tok.decode([int(t) for t in np.load(tmp_path / "out" / "val.npy")])
    # o último documento em ordem alfabética é o 11 — não pode ser "o val"
    assert not val.strip().startswith("doc11")


def test_split_e_reprodutivel_por_semente(tmp_path):
    corpus = _corpus(tmp_path)
    a = build_dataset(corpus, tmp_path / "a", vocab_size=300, val_fraction=0.2,
                      verbose=False, seed=42)
    b = build_dataset(corpus, tmp_path / "b", vocab_size=300, val_fraction=0.2,
                      verbose=False, seed=42)
    c = build_dataset(corpus, tmp_path / "c", vocab_size=300, val_fraction=0.2,
                      verbose=False, seed=43)
    np.testing.assert_array_equal(np.load(tmp_path / "a" / "val.npy"),
                                  np.load(tmp_path / "b" / "val.npy"))
    assert a["val_tokens"] == b["val_tokens"]
    assert not np.array_equal(np.load(tmp_path / "a" / "val.npy"),
                              np.load(tmp_path / "c" / "val.npy")) or a == c


def test_corpus_de_um_documento_avisa_e_cai_na_cauda(tmp_path):
    corpus = _corpus(tmp_path, n_docs=1)
    meta = build_dataset(corpus, tmp_path / "out", vocab_size=300,
                         val_fraction=0.2, verbose=False)
    assert meta["val_docs"] == 0 and "cauda" in meta["split"]
    assert meta["val_tokens"] > 0                 # ainda dá pra medir algo
    assert meta["train_tokens"] + meta["val_tokens"] == meta["tokens"]


def test_pick_val_docs_nunca_leva_o_corpus_inteiro():
    por_doc = [[1, 2, 3], [4, 5, 6]]
    assert len(_pick_val_docs(por_doc, 0.99, np.random.default_rng(0))) <= 1
    assert _pick_val_docs(por_doc, 0.0, np.random.default_rng(0)) == set()
    assert _pick_val_docs([[1, 2]], 0.5, np.random.default_rng(0)) == set()


def test_amostra_do_tokenizer_nao_e_so_o_primeiro_documento():
    """E14: treinar o BPE em 'os primeiros N chars' pega uma fonte só."""
    docs = [f"documento {i} " + "conteudo especifico " * 20 for i in range(20)]
    amostra = _sample_docs(docs, sample_chars=400, rng=np.random.default_rng(0))
    assert len(amostra) <= 400
    assert not amostra.startswith("documento 0 ")   # não é a ordem original
    assert amostra                                   # e não veio vazia


def test_meta_registra_a_procedencia_do_split(tmp_path):
    build_dataset(_corpus(tmp_path), tmp_path / "out", vocab_size=300,
                  val_fraction=0.2, verbose=False, seed=5)
    meta = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    assert meta["seed"] == 5 and meta["val_docs"] >= 1


# ── E27: a última janela válida tem que ser sorteável ────────────────────
def test_get_batch_alcanca_a_ultima_janela():
    tokens = np.arange(20, dtype=np.uint16)
    block = 4
    vistos = set()
    rng = np.random.default_rng(0)
    for _ in range(200):
        x, y = get_batch(tokens, block, 8, rng)
        vistos.update(int(row[0]) for row in x)
    assert max(vistos) == len(tokens) - block - 1   # último início válido
    assert min(vistos) == 0


def test_get_batch_nunca_sai_do_corpus():
    tokens = np.arange(20, dtype=np.uint16)
    rng = np.random.default_rng(1)
    for _ in range(100):
        x, y = get_batch(tokens, 4, 8, rng)
        assert x.shape == y.shape == (8, 4)
        np.testing.assert_array_equal(y[:, :-1], x[:, 1:])   # y é x deslocado


# ── E25: decode não some com id desconhecido em silêncio ─────────────────
def test_decode_avisa_id_fora_do_vocabulario(caplog):
    from src.nanollm.tokenizer import ByteBPETokenizer

    tok = ByteBPETokenizer()
    tok.train("texto simples para treinar o bpe " * 20, vocab_size=300)
    ids = tok.encode("texto")
    with caplog.at_level("WARNING"):
        saida = tok.decode(ids + [99_999])
    assert saida == "texto"                        # robusto: não quebra
    assert any("fora do vocabul" in r.message for r in caplog.records)


def test_decode_limpo_nao_loga(caplog):
    from src.nanollm.tokenizer import ByteBPETokenizer

    tok = ByteBPETokenizer()
    tok.train("texto simples para treinar o bpe " * 20, vocab_size=300)
    with caplog.at_level("WARNING"):
        tok.decode(tok.encode("texto simples"))
    assert not [r for r in caplog.records if "tokenizer" in r.message]


@pytest.mark.parametrize("frac", [0.0, 0.1, 0.5])
def test_fracoes_de_val_respeitadas_aproximadamente(tmp_path, frac):
    meta = build_dataset(_corpus(tmp_path, n_docs=20), tmp_path / f"o{frac}",
                         vocab_size=300, val_fraction=frac, verbose=False)
    if frac == 0.0:
        assert meta["val_tokens"] == 0
    else:
        real = meta["val_tokens"] / meta["tokens"]
        assert abs(real - frac) < 0.12          # granularidade é o documento
