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


def build_dataset(
    corpus_dir: str | Path,
    out_dir: str | Path,
    vocab_size: int = 4096,
    sample_chars: int = 2_000_000,
    val_fraction: float = 0.02,
    verbose: bool = True,
) -> dict:
    """Treina o tokenizer e tokeniza o corpus. Retorna o meta dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    docs = read_corpus(corpus_dir)
    if not docs:
        raise FileNotFoundError(f"nenhum .txt com conteúdo em {corpus_dir}")
    total_chars = sum(len(d) for d in docs)

    t0 = time.time()
    tok = ByteBPETokenizer()
    sample = "\n".join(docs)[:sample_chars]
    if verbose:
        print(f"corpus: {len(docs)} docs, {total_chars:,} chars")
        print(f"treinando tokenizer (vocab {vocab_size}, amostra {len(sample):,} chars)...")
    tok.train(sample, vocab_size=vocab_size, verbose=verbose)
    tok.save(out / "tokenizer.json")
    if verbose:
        print(f"tokenizer pronto em {time.time() - t0:.1f}s (vocab real {tok.vocab_size})")

    ids: list[int] = []
    for i, doc in enumerate(docs):
        ids.extend(tok.encode(doc))
        ids.append(tok.sep_id)
        if verbose and (i + 1) % 50 == 0:
            print(f"  tokenizados {i + 1}/{len(docs)} docs")
    if tok.vocab_size > np.iinfo(np.uint16).max:
        raise ValueError("vocab > 65535 não cabe em uint16")
    tokens = np.array(ids, dtype=np.uint16)

    n_val = max(int(len(tokens) * val_fraction), 0)
    np.save(out / "train.npy", tokens[: len(tokens) - n_val])
    np.save(out / "val.npy", tokens[len(tokens) - n_val :])

    meta = {
        "docs": len(docs),
        "chars": total_chars,
        "tokens": int(len(tokens)),
        "train_tokens": int(len(tokens) - n_val),
        "val_tokens": int(n_val),
        "vocab_size": tok.vocab_size,
        "chars_per_token": round(total_chars / max(len(tokens), 1), 3),
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
    ix = rng.integers(0, len(tokens) - block_size - 1, size=batch_size)
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
    args = ap.parse_args()
    build_dataset(args.corpus, args.out, args.vocab_size, args.sample_chars, args.val_fraction)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    main()
