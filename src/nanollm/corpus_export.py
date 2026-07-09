"""Exportador de corpus soberano: o que o Apolo sabe → data/nanollm/corpus/.

Épicos 1.1 + 1.2 do APOLO_NANO_ROADMAP. Varre os bancos LOCAIS do Apolo
(somente leitura) e produz .txt limpos para treinar o Apolo-Nano:

    - learned_topics (apolo.db)      → sínteses do aprendizado autônomo
    - episodes (apolo.db)            → memória autobiográfica datada
    - knowledge (local_knowledge.db) → base de conhecimento FTS

Higiene aplicada (determinística, testável):
    - normalização de espaços/linhas
    - linhas com cara de segredo NUNCA saem (api key, senha, token, JWT…)
    - filtro de português por razão de stopwords (--keep-non-pt desliga)
    - dedup global por hash de parágrafo normalizado
    - registro mínimo de --min-chars (descarta ruído de título solto)

Uso:
    python -m src.nanollm.corpus_export --db data/apolo.db \
        --knowledge data/local_knowledge.db --out data/nanollm/corpus

Grava um arquivo por fonte (registros separados por DOC_SEPARATOR, que o
src.nanollm.data entende como fronteira de documento) + report.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path

# Fronteira de documento DENTRO de um .txt de corpus (ver data.read_corpus).
DOC_SEPARATOR = "\n\n<<<|DOC|>>>\n\n"

# Linhas contendo qualquer um destes padrões são descartadas inteiras.
_SECRET_RES = [
    re.compile(r"(?i)\b(api[_-]?key|secret|senha|password|passwd|token|credencial)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),          # chaves estilo OpenAI/Anthropic
    re.compile(r"\beyJ[A-Za-z0-9_-]{16,}"),           # JWT
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"\b[0-9a-fA-F]{40,}\b"),              # hex longo (hashes/keys)
    re.compile(r"(?i)postgres(ql)?://[^\s]+:[^\s]+@"),  # DSN com senha
]

# Stopwords DISTINTIVAS de PT (evitadas as ambíguas com EN tipo "a", "as", "no").
_PT_STOPWORDS = frozenset(
    "de que não nao uma para com é dos das um os como mais foi são sao já ja "
    "também tambem pelo pela até ate isso ela entre depois sem mesmo aos seus "
    "quem nas esse essa você voce eles elas está esta são ser tem mas ou se "
    "por sua seu quando muito nos ao então entao".split()
)

_WORD_RE = re.compile(r"[a-záàâãéêíóôõúüç]+", re.IGNORECASE)


def portuguese_score(text: str) -> float:
    """Fração das palavras que são stopwords PT distintivas (0..1)."""
    words = _WORD_RE.findall(text.lower())
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in _PT_STOPWORDS)
    return hits / len(words)


def is_portuguese(text: str, threshold: float = 0.08) -> bool:
    return portuguese_score(text) >= threshold


def has_secret(line: str) -> bool:
    return any(r.search(line) for r in _SECRET_RES)


def clean_text(text: str) -> str:
    """Normaliza espaços/linhas e REMOVE linhas com cara de segredo."""
    text = unicodedata.normalize("NFC", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c == "\n" or c == "\t" or ord(c) >= 32)
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).rstrip()
        if has_secret(line):
            continue
        lines.append(line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)  # no máx. 1 linha em branco seguida
    return out.strip()


def _paragraph_hashes(text: str) -> list[tuple[str, str]]:
    """[(hash, parágrafo)] com hash de forma normalizada (case/espaço-insensível)."""
    out = []
    for para in text.split("\n\n"):
        norm = re.sub(r"\s+", " ", para).strip().lower()
        if norm:
            out.append((hashlib.sha1(norm.encode("utf-8")).hexdigest(), para))
    return out


class Deduper:
    """Dedup GLOBAL por parágrafo: a 2ª ocorrência de um parágrafo é removida."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self.dropped = 0

    def apply(self, text: str) -> str:
        kept = []
        for h, para in _paragraph_hashes(text):
            if h in self._seen:
                self.dropped += 1
                continue
            self._seen.add(h)
            kept.append(para)
        return "\n\n".join(kept)


# ------------------------------------------------------------------ fontes
def _ro_connect(path: Path) -> sqlite3.Connection:
    """Conexão SOMENTE LEITURA (o app pode estar no ar usando o banco)."""
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def _fetch(path: Path, sql: str) -> list[tuple]:
    if not path.exists():
        return []
    con = _ro_connect(path)
    try:
        return con.execute(sql).fetchall()
    except sqlite3.OperationalError:  # tabela não existe nesse banco
        return []
    finally:
        con.close()


def fetch_topics(db: Path) -> list[str]:
    rows = _fetch(db, "SELECT topic, category, summary FROM learned_topics "
                      "WHERE summary IS NOT NULL AND summary != '' ORDER BY id")
    return [f"Tópico: {t}\nCategoria: {c or 'web'}\n\n{s}" for t, c, s in rows]


def fetch_episodes(db: Path) -> list[str]:
    rows = _fetch(db, "SELECT occurred_at, title, summary FROM episodes ORDER BY id")
    docs = []
    for when, title, summary in rows:
        day = str(when or "")[:10]
        body = f"\n\n{summary}" if summary else ""
        docs.append(f"Episódio de {day}: {title}{body}")
    return docs


def fetch_knowledge(db: Path) -> list[str]:
    rows = _fetch(db, "SELECT title, content FROM knowledge "
                      "WHERE content IS NOT NULL AND content != '' ORDER BY id")
    return [f"{t}\n\n{c}" for t, c in rows]


def fetch_supabase(env_file: str | Path | None = None, limit: int = 5000) -> list[str]:
    """Base de conhecimento no Supabase (dados do Leo na nuvem), leitura só.

    Import tardio: o exportador continua funcionando sem supabase instalado.
    """
    import os

    if env_file:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not (url and key):
        return []
    from src.knowledge import SupabaseKnowledge

    rows = SupabaseKnowledge(url, key).all_rows(limit=limit)
    return [
        f"{r.get('title', '')}\n\n{r.get('content', '')}"
        for r in rows
        if r.get("content")
    ]


# ------------------------------------------------------------------ export
def export_corpus(
    db: str | Path = "data/apolo.db",
    knowledge_db: str | Path = "data/local_knowledge.db",
    out_dir: str | Path = "data/nanollm/corpus",
    min_chars: int = 200,
    require_pt: bool = True,
    extra_dirs: list[str | Path] | None = None,
    supabase_env: str | Path | None = None,
) -> dict:
    """Exporta todas as fontes. Retorna o relatório de composição."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dedup = Deduper()
    report: dict = {"sources": {}, "filters": {"min_chars": min_chars, "require_pt": require_pt}}

    sources: list[tuple[str, list[str]]] = [
        ("apolo_topics", fetch_topics(Path(db))),
        ("apolo_episodes", fetch_episodes(Path(db))),
        ("apolo_knowledge", fetch_knowledge(Path(knowledge_db))),
    ]
    if supabase_env is not None:
        sources.append(("apolo_supabase", fetch_supabase(supabase_env)))
    for d in extra_dirs or []:
        docs = [p.read_text(encoding="utf-8", errors="ignore")
                for p in sorted(Path(d).rglob("*.txt")) if p.is_file()]
        sources.append((f"docs_{Path(d).name}", docs))

    total_chars = 0
    for name, raw_docs in sources:
        kept: list[str] = []
        skipped_small = skipped_lang = 0
        for doc in raw_docs:
            doc = clean_text(doc)
            doc = dedup.apply(doc)
            if len(doc) < min_chars:
                skipped_small += 1
                continue
            if require_pt and not is_portuguese(doc):
                skipped_lang += 1
                continue
            kept.append(doc)
        chars = sum(len(d) for d in kept)
        total_chars += chars
        report["sources"][name] = {
            "registros": len(raw_docs), "mantidos": len(kept), "chars": chars,
            "descartados_pequenos": skipped_small, "descartados_idioma": skipped_lang,
        }
        path = out / f"{name}.txt"
        if kept:
            path.write_text(DOC_SEPARATOR.join(kept), encoding="utf-8")
        elif path.exists():
            path.unlink()  # não deixa export velho para trás

    report["paragrafos_duplicados_removidos"] = dedup.dropped
    report["chars_total"] = total_chars
    report["tokens_estimados"] = int(total_chars / 2.9)  # razão medida no smoke
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Exporta o conhecimento do Apolo como corpus")
    ap.add_argument("--db", default="data/apolo.db")
    ap.add_argument("--knowledge", default="data/local_knowledge.db")
    ap.add_argument("--out", default="data/nanollm/corpus")
    ap.add_argument("--min-chars", type=int, default=200)
    ap.add_argument("--keep-non-pt", action="store_true",
                    help="não filtrar registros que não parecem português")
    ap.add_argument("--docs", nargs="*", default=[],
                    help="pastas extras com .txt do usuário")
    ap.add_argument("--supabase-env", default=None,
                    help="caminho do .env com SUPABASE_URL/KEY p/ exportar a base da nuvem")
    args = ap.parse_args()
    report = export_corpus(args.db, args.knowledge, args.out, args.min_chars,
                           require_pt=not args.keep_non_pt, extra_dirs=args.docs,
                           supabase_env=args.supabase_env)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
