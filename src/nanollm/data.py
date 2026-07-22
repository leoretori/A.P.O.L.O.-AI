"""Preparação de corpus: .txt → tokenizer treinado + tokens.npy.

Uso:
    python -m src.nanollm.data --corpus data/nanollm/corpus --out data/nanollm \
        --vocab-size 4096

Coloque arquivos .txt (UTF-8) em data/nanollm/corpus/. Cada arquivo é um
documento; documentos são unidos com o token <|sep|>. O tokenizer treina
numa amostra (--sample-chars) e o corpus inteiro é tokenizado.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from src.nanollm.tokenizer import ByteBPETokenizer


def read_corpus(corpus_dir: str | Path) -> list[str]:
    """Lê todos os .txt (recursivo, ordenado) como documentos.

    Um arquivo pode conter VÁRIOS documentos separados por DOC_SEPARATOR
    (formato do corpus_export); arquivo sem separador é 1 documento.
    """
    from src.nanollm.corpus_export import DOC_SEPARATOR

    root = Path(corpus_dir)
    docs = []
    for path in sorted(root.rglob("*.txt")):
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        for doc in text.split(DOC_SEPARATOR):
            doc = doc.strip()
            if doc:
                docs.append(doc)
    return docs


def _sample_docs(docs: list[str], sample_chars: int,
                 rng: np.random.Generator) -> str:
    """Amostra para treinar o tokenizer: documentos SORTEADOS até o teto de
    chars — não "os primeiros N chars da ordem alfabética" (E14), que treinava
    o BPE numa fonte só."""
    partes: list[str] = []
    n = 0
    for i in rng.permutation(len(docs)):
        if n >= sample_chars:
            break
        partes.append(docs[int(i)])
        n += len(docs[int(i)])
    return "\n".join(partes)[:sample_chars]


def _pick_val_docs(por_doc: list[list[int]], val_fraction: float,
                   rng: np.random.Generator) -> set[int]:
    """Escolhe DOCUMENTOS inteiros para o val até cobrir `val_fraction` dos
    tokens. Nunca leva o corpus todo (com 1 documento, devolve vazio)."""
    if val_fraction <= 0 or len(por_doc) < 2:
        return set()
    alvo = int(sum(len(d) for d in por_doc) * val_fraction)
    escolhidos: set[int] = set()
    acumulado = 0
    for i in rng.permutation(len(por_doc)):
        if acumulado >= alvo or len(escolhidos) >= len(por_doc) - 1:
            break
        escolhidos.add(int(i))
        acumulado += len(por_doc[int(i)])
    return escolhidos


def build_dataset(
    corpus_dir: str | Path,
    out_dir: str | Path,
    vocab_size: int = 4096,
    sample_chars: int = 2_000_000,
    val_fraction: float = 0.02,
    verbose: bool = True,
    seed: int = 1337,
) -> dict:
    """Treina o tokenizer e tokeniza o corpus. Retorna o meta dict.

    Split de validação **por DOCUMENTO, sorteado com semente fixa** (E14). Antes
    o val era a cauda de tokens do corpus concatenado — ou seja, o fim do último
    arquivo em ordem alfabética: uma fonte só, com distribuição diferente do
    treino. Todo `best_val`/early-stop otimizava contra um val enviesado. A
    amostra do tokenizer também é sorteada por documento pelo mesmo motivo.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docs = read_corpus(corpus_dir)
    if not docs:
        raise FileNotFoundError(f"nenhum .txt com conteúdo em {corpus_dir}")
    total_chars = sum(len(d) for d in docs)
    rng = np.random.default_rng(seed)

    t0 = time.time()
    tok = ByteBPETokenizer()
    sample = _sample_docs(docs, sample_chars, rng)
    if verbose:
        print(f"corpus: {len(docs)} docs, {total_chars:,} chars")
        print(f"treinando tokenizer (vocab {vocab_size}, amostra {len(sample):,} chars)...")
    tok.train(sample, vocab_size=vocab_size, verbose=verbose)
    tok.save(out / "tokenizer.json")
    if verbose:
        print(f"tokenizer pronto em {time.time() - t0:.1f}s (vocab real {tok.vocab_size})")

    if tok.vocab_size > np.iinfo(np.uint16).max:
        raise ValueError("vocab > 65535 não cabe em uint16")

    por_doc: list[list[int]] = []
    for i, doc in enumerate(docs):
        por_doc.append(tok.encode(doc) + [tok.sep_id])
        if verbose and (i + 1) % 50 == 0:
            print(f"  tokenizados {i + 1}/{len(docs)} docs")
    n_tokens = sum(len(d) for d in por_doc)

    val_docs = _pick_val_docs(por_doc, val_fraction, rng)
    train_ids: list[int] = []
    val_ids: list[int] = []
    for i, d in enumerate(por_doc):
        (val_ids if i in val_docs else train_ids).extend(d)
    if not val_docs and val_fraction > 0:
        # corpus de 1 documento: não dá para separar por documento sem zerar o
        # treino — cai na cauda, como antes, mas DIZENDO que caiu.
        n_val = max(int(n_tokens * val_fraction), 0)
        if n_val:
            val_ids = train_ids[len(train_ids) - n_val:]
            train_ids = train_ids[: len(train_ids) - n_val]
            if verbose:
                print(f"⚠️ corpus de {len(docs)} documento(s): split por documento "
                      f"impossível, usando a cauda ({n_val:,} tokens). O val NÃO é "
                      f"independente do treino.")

    np.save(out / "train.npy", np.array(train_ids, dtype=np.uint16))
    np.save(out / "val.npy", np.array(val_ids, dtype=np.uint16))

    meta = {
        "docs": len(docs),
        "chars": total_chars,
        "tokens": int(n_tokens),
        "train_tokens": int(len(train_ids)),
        "val_tokens": int(len(val_ids)),
        "val_docs": len(val_docs),
        "split": "por documento (semente fixa)" if val_docs else "cauda (1 documento)",
        "seed": seed,
        "vocab_size": tok.vocab_size,
        "chars_per_token": round(total_chars / max(n_tokens, 1), 3),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if verbose:
        print(f"dataset: {meta['tokens']:,} tokens "
              f"({meta['chars_per_token']} chars/token) → {out}")
    return meta


def load_tokens(path: str | Path) -> np.ndarray:
    return np.load(path, mmap_mode="r")


def get_batch(
    tokens: np.ndarray, block_size: int, batch_size: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray]:
    """Sorteia janelas (x, y) com y deslocado 1 token à frente."""
    if len(tokens) < block_size + 2:
        raise ValueError(f"corpus com {len(tokens)} tokens < block_size+2")
    # `high` é EXCLUSIVO: com `- block_size - 1` a última janela válida
    # (start = len-block-1) nunca era sorteada — os últimos tokens do corpus
    # só apareciam como alvo, nunca como início de janela (E27).
    ix = rng.integers(0, len(tokens) - block_size, size=batch_size)
    x = np.stack([tokens[i : i + block_size] for i in ix]).astype(np.int64)
    y = np.stack([tokens[i + 1 : i + 1 + block_size] for i in ix]).astype(np.int64)
    return x, y


def main() -> None:
    ap = argparse.ArgumentParser(description="Prepara corpus do Apolo-Nano")
    ap.add_argument("--corpus", default="data/nanollm/corpus", help="pasta com .txt")
    ap.add_argument("--out", default="data/nanollm", help="pasta de saída")
    ap.add_argument("--vocab-size", type=int, default=4096)
    ap.add_argument("--sample-chars", type=int, default=2_000_000,
                    help="chars usados p/ treinar o tokenizer")
    ap.add_argument("--val-fraction", type=float, default=0.02)
    ap.add_argument("--seed", type=int, default=1337,
                    help="semente do split por documento e da amostra do tokenizer")
    args = ap.parse_args()
    build_dataset(args.corpus, args.out, args.vocab_size, args.sample_chars,
                  args.val_fraction, seed=args.seed)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
