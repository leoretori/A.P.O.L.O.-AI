"""Tokenizer BPE do zero + preparação de dataset (src/nanollm)."""

import numpy as np
import pytest

from src.nanollm.data import build_dataset, get_batch, load_tokens
from src.nanollm.tokenizer import SEP_TOKEN, ByteBPETokenizer

CORPUS_PT = (
    "O Apolo é um assistente pessoal. O Apolo aprende sozinho todos os dias. "
    "A memória do Apolo guarda episódios, lições e conhecimento. "
    "Construção, coração, atenção — acentuação não pode quebrar o tokenizer! "
    "Emoji também: 🚀🧠. E código: def apolo(x): return x + 1\n"
) * 20


@pytest.fixture()
def tok() -> ByteBPETokenizer:
    t = ByteBPETokenizer()
    t.train(CORPUS_PT, vocab_size=400)
    return t


def test_roundtrip_preserva_texto(tok):
    for text in [CORPUS_PT[:300], "acentuação: ção çã õ 🚀", "linha1\n  linha2\ttab", ""]:
        assert tok.decode(tok.encode(text)) == text


def test_bpe_comprime(tok):
    ids = tok.encode("O Apolo aprende sozinho todos os dias.")
    raw_bytes = len("O Apolo aprende sozinho todos os dias.".encode("utf-8"))
    assert len(ids) < raw_bytes  # merges aprendidos comprimem de verdade


def test_vocab_size_e_sep(tok):
    assert tok.vocab_size <= 400
    assert tok.sep_id == tok.vocab_size - 1
    assert tok.special[SEP_TOKEN] == tok.sep_id
    assert tok.decode([tok.sep_id]) == SEP_TOKEN


def test_encode_deterministico(tok):
    assert tok.encode(CORPUS_PT[:200]) == tok.encode(CORPUS_PT[:200])


def test_save_load_identico(tok, tmp_path):
    path = tmp_path / "tok.json"
    tok.save(path)
    tok2 = ByteBPETokenizer.load(path)
    assert tok2.merges == tok.merges
    assert tok2.vocab_size == tok.vocab_size
    sample = "O Apolo é meu — atenção! 🚀"
    assert tok2.encode(sample) == tok.encode(sample)
    assert tok2.decode(tok.encode(sample)) == sample


def test_bytes_fora_do_treino_nao_quebram(tok):
    exotic = "中文 русский العربية ¯\\_(ツ)_/¯"
    assert tok.decode(tok.encode(exotic)) == exotic


def test_build_dataset_end_to_end(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "doc1.txt").write_text(CORPUS_PT, encoding="utf-8")
    (corpus / "doc2.txt").write_text("Segundo documento do Apolo. " * 50, encoding="utf-8")
    out = tmp_path / "ds"

    meta = build_dataset(corpus, out, vocab_size=300, val_fraction=0.1, verbose=False)

    assert meta["docs"] == 2
    assert meta["tokens"] == meta["train_tokens"] + meta["val_tokens"]
    assert meta["val_tokens"] > 0
    train = load_tokens(out / "train.npy")
    assert train.dtype == np.uint16
    assert int(train.max()) < meta["vocab_size"]
    tok = ByteBPETokenizer.load(out / "tokenizer.json")
    assert tok.vocab_size == meta["vocab_size"]
    # documentos separados por <|sep|> no fluxo completo (train+val)
    full = np.concatenate([np.load(out / "train.npy"), np.load(out / "val.npy")])
    assert (full == tok.sep_id).sum() == 2  # um sep por documento


def test_build_dataset_sem_corpus(tmp_path):
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    with pytest.raises(FileNotFoundError):
        build_dataset(vazio, tmp_path / "ds", verbose=False)


def test_get_batch_shapes():
    tokens = np.arange(1000, dtype=np.uint16) % 50
    rng = np.random.default_rng(0)
    x, y = get_batch(tokens, block_size=32, batch_size=4, rng=rng)
    assert x.shape == (4, 32) and y.shape == (4, 32)
    assert x.dtype == np.int64
    np.testing.assert_array_equal(y[:, :-1], x[:, 1:])  # y é x deslocado em 1


def test_get_batch_corpus_pequeno():
    with pytest.raises(ValueError):
        get_batch(np.zeros(5, dtype=np.uint16), 32, 4, np.random.default_rng(0))
