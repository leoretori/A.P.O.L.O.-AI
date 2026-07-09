"""Dataset de TAREFA para o fine-tune do Apolo-Nano (Épico 4.1).

O v1 é um modelo BASE (só completa texto). Para ele APRENDER uma tarefa, a
ensinamos como um padrão de continuação consistente e a treinamos nele:

    título:   "{texto}\\n\\nTópico: {título}<|sep|>"

Os pares saem 100% do banco LOCAL do Apolo — é destilação soberana: o LLM
grande já produziu esses títulos/setores durante o aprendizado autônomo, e
agora o modelo próprio aprende a imitá-los. Fontes:

    - learned_topics.summary → .topic     (centenas de pares "texto → título")
    - session_meta.title ← 1ª msg user    (títulos de conversa reais, poucos)

Reusa o MESMO tokenizer do checkpoint (fine-tune não pode trocar o vocab).

Uso:
    python -m src.nanollm.taskdata --db data/apolo.db \
        --tokenizer data/nanollm/ckpt_v1/tokenizer.json --out data/nanollm/tasks
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import numpy as np

from src.nanollm.corpus_export import clean_text, is_portuguese
from src.nanollm.tokenizer import ByteBPETokenizer

# Mesmo padrão que src.nanollm.tasks.title_prompt usa na inferência.
TITLE_TEMPLATE = "{context}\n\nTópico: {title}"
# Classificação de setor (tarefa FECHADA — joga a favor de um modelo pequeno).
SECTOR_TEMPLATE = "{context}\n\nSetor: {label}"
SECTOR_MIN_EXAMPLES = 25  # setores com menos exemplos que isto são descartados
_CONTEXT_CHARS = 240  # regime parecido com o da 1ª mensagem de conversa (200)

# Ruído de scraping nas sínteses: linhas só-URL, cabeçalho markdown "**Fonte**",
# separadores. Removidas para o contexto virar PROSA (a distribuição da
# inferência é a 1ª mensagem limpa do usuário, não uma página raspada).
_URL_LINE = re.compile(r"^\s*(URL:\s*)?https?://\S+\s*$", re.MULTILINE)
_MD_BOLD_LINE = re.compile(r"^\s*\*\*.*\*\*\s*$", re.MULTILINE)
_MD_MARKS = re.compile(r"[*_`#>]+")


def _prose_context(text: str) -> str:
    """Tira URL/markdown/separador e devolve a 1ª janela de prosa contínua."""
    text = clean_text(text)
    text = _URL_LINE.sub("", text)
    text = _MD_BOLD_LINE.sub("", text)
    text = text.replace("---", " ")
    text = _MD_MARKS.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", " ", text).replace("\n", " ").strip()
    return text[:_CONTEXT_CHARS].strip()


# Marcadores de inglês: os topics de web_search são queries em inglês e o
# modelo é PT-BR. Se o título tem qualquer um destes, é inglês → descartado.
_EN_MARKERS = frozenset(
    "the of and for with how what why when using based guide explained "
    "principles fundamentals best practices introduction overview tutorial "
    "to is are your you a an in on step steps".split()
)


def _looks_english(title: str) -> bool:
    words = {w.lower() for w in re.findall(r"[a-zA-Z]+", title)}
    return bool(words & _EN_MARKERS)


def _valid_title(title: str) -> bool:
    """Título de treino tem que ser curto, limpo e em PT (senão ensina lixo)."""
    title = (title or "").strip()
    if not (3 <= len(title) <= 60) or len(title.split()) > 8:
        return False
    if "\n" in title or re.search(r"(https?://|```|\|)", title):
        return False
    return not _looks_english(title)


def _title_pairs_from_topics(con: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT topic, summary FROM learned_topics "
        "WHERE summary != '' AND topic != '' ORDER BY id"
    ).fetchall()
    pairs = []
    for topic, summary in rows:
        title = topic.strip()
        context = _prose_context(summary)
        # título E contexto em PT: os topics de web_search são queries em inglês;
        # o modelo é PT-BR, então pares em inglês só atrapalhariam.
        if _valid_title(title) and len(context) >= 40 and is_portuguese(context):
            pairs.append((context, title))
    return pairs


def _title_pairs_from_sessions(con: sqlite3.Connection) -> list[tuple[str, str]]:
    rows = con.execute(
        "SELECT m.title, (SELECT content FROM session_messages sm "
        "  WHERE sm.session_id=m.session_id AND sm.role='user' "
        "  ORDER BY sm.id LIMIT 1) FROM session_meta m"
    ).fetchall()
    pairs = []
    for title, first_msg in rows:
        if not (title and first_msg):
            continue
        title = title.strip()
        context = clean_text(first_msg)[:_CONTEXT_CHARS].strip()
        if _valid_title(title) and len(context) >= 3:
            pairs.append((context, title))
    return pairs


def _dedup_by_context(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    unique = []
    for ctx, out in pairs:
        key = ctx[:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append((ctx, out))
    return unique


def collect_title_pairs(db: str | Path) -> list[tuple[str, str]]:
    """Todos os pares (contexto → título) do banco, sem duplicatas de contexto."""
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        pairs = _title_pairs_from_topics(con) + _title_pairs_from_sessions(con)
    finally:
        con.close()
    return _dedup_by_context(pairs)


def collect_sector_pairs(
    db: str | Path, min_examples: int = SECTOR_MIN_EXAMPLES
) -> tuple[list[tuple[str, str]], list[str]]:
    """Pares (contexto → setor) rotulados por classify_sector.

    Só mantém setores com >= min_examples (conjunto FECHADO e representado);
    os tópicos de setores raros são descartados (não viram 'outros' inflado).
    Retorna (pares, rótulos_ordenados).
    """
    from collections import Counter

    from src.topics import classify_sector

    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT topic, summary FROM learned_topics WHERE topic != ''"
        ).fetchall()
    finally:
        con.close()

    raw: list[tuple[str, str]] = []
    for topic, summary in rows:
        sector = classify_sector(f"{topic} {(summary or '')[:200]}")
        context = _prose_context(f"{topic}. {summary or ''}")
        if len(context) >= 20:
            raw.append((context, sector))

    counts = Counter(s for _, s in raw)
    keep = {s for s, n in counts.items() if n >= min_examples}
    pairs = _dedup_by_context([(c, s) for c, s in raw if s in keep])
    labels = sorted({s for _, s in pairs})
    return pairs, labels


def _write_tokenized(
    examples: list[str], tok: ByteBPETokenizer, out: Path,
    val_fraction: float, seed: int,
) -> dict:
    """Tokeniza os exemplos, faz split train/val determinístico e salva .npy."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(examples))
    n_val = max(int(len(examples) * val_fraction), 1)
    val_set = set(order[:n_val].tolist())

    def _encode_subset(want_val: bool) -> np.ndarray:
        buf: list[int] = []
        for i, ex in enumerate(examples):
            if (i in val_set) == want_val:
                buf.extend(tok.encode(ex))
                buf.append(tok.sep_id)
        return np.array(buf, dtype=np.uint16)

    train_tokens = _encode_subset(False)
    val_tokens = _encode_subset(True)
    np.save(out / "train.npy", train_tokens)
    np.save(out / "val.npy", val_tokens)
    return {
        "tokens": int(len(train_tokens) + len(val_tokens)),
        "train_tokens": int(len(train_tokens)),
        "val_tokens": int(len(val_tokens)),
        "vocab_size": tok.vocab_size,
    }


def build_task_dataset(
    db: str | Path,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    val_fraction: float = 0.1,
    seed: int = 42,
    verbose: bool = True,
) -> dict:
    """Monta o dataset de título e o tokeniza com o tokenizer do checkpoint."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tok = ByteBPETokenizer.load(tokenizer_path)

    pairs = collect_title_pairs(db)
    if not pairs:
        raise ValueError("nenhum par de tarefa encontrado no banco")

    examples = [TITLE_TEMPLATE.format(context=c, title=t) for c, t in pairs]
    (out / "pairs.jsonl").write_text(
        "\n".join(json.dumps({"context": c, "title": t}, ensure_ascii=False)
                  for c, t in pairs),
        encoding="utf-8",
    )

    meta = {"task": "title", "pairs": len(pairs), "template": TITLE_TEMPLATE}
    meta.update(_write_tokenized(examples, tok, out, val_fraction, seed))
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    if verbose:
        print(f"dataset de título: {meta['pairs']} pares → {meta['tokens']:,} tokens "
              f"(train {meta['train_tokens']:,} / val {meta['val_tokens']:,}) → {out}")
    return meta


def build_sector_dataset(
    db: str | Path,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    val_fraction: float = 0.15,
    seed: int = 42,
    min_examples: int = SECTOR_MIN_EXAMPLES,
    verbose: bool = True,
) -> dict:
    """Monta o dataset de CLASSIFICAÇÃO de setor (tarefa fechada)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tok = ByteBPETokenizer.load(tokenizer_path)

    pairs, labels = collect_sector_pairs(db, min_examples)
    if not pairs:
        raise ValueError("nenhum par de setor encontrado no banco")

    examples = [SECTOR_TEMPLATE.format(context=c, label=s) for c, s in pairs]
    (out / "pairs.jsonl").write_text(
        "\n".join(json.dumps({"context": c, "label": s}, ensure_ascii=False)
                  for c, s in pairs),
        encoding="utf-8",
    )

    from collections import Counter
    meta = {
        "task": "sector",
        "pairs": len(pairs),
        "labels": labels,
        "label_counts": dict(Counter(s for _, s in pairs)),
        "template": SECTOR_TEMPLATE,
    }
    meta.update(_write_tokenized(examples, tok, out, val_fraction, seed))
    (out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    if verbose:
        print(f"dataset de setor: {meta['pairs']} pares, {len(labels)} classes "
              f"→ {meta['tokens']:,} tokens → {out}")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Monta o dataset de tarefa do Apolo-Nano")
    ap.add_argument("--task", choices=["title", "sector"], default="title")
    ap.add_argument("--db", default="data/apolo.db")
    ap.add_argument("--tokenizer", default="data/nanollm/ckpt_v1/tokenizer.json")
    ap.add_argument("--out", default=None, help="padrão: data/nanollm/{task}s")
    ap.add_argument("--val-fraction", type=float, default=None)
    args = ap.parse_args()
    if args.task == "sector":
        out = args.out or "data/nanollm/sectors"
        build_sector_dataset(args.db, args.tokenizer, out,
                             args.val_fraction if args.val_fraction is not None else 0.15)
    else:
        out = args.out or "data/nanollm/tasks"
        build_task_dataset(args.db, args.tokenizer, out,
                          args.val_fraction if args.val_fraction is not None else 0.1)


if __name__ == "__main__":
    main()
