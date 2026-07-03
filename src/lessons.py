"""
A.P.O.L.O. Lessons — memória de lições aprendidas do Coder.

Cada tarefa do Coder pode deixar uma lição: um erro que a guarda de regressão
reverteu, um comando que falhou repetidamente, ou uma reflexão pós-tarefa.
Nas tarefas seguintes, as lições relevantes são injetadas no system prompt —
o Coder literalmente aprende com a própria experiência, como o memory do
Claude Code.

Armazenamento: SQLite próprio (data/lessons.db), sem dependências novas.
Recall: score lexical por sobreposição de tokens (rápido, sem LLM/embeddings).
"""

import logging
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime

logger = logging.getLogger(__name__)

# Stopwords PT/EN — palavras que não discriminam tarefa nenhuma.
_STOPWORDS = {
    "a", "o", "e", "de", "do", "da", "dos", "das", "em", "no", "na", "nos", "nas",
    "um", "uma", "que", "com", "por", "para", "pra", "se", "ao", "aos", "as", "os",
    "como", "mais", "mas", "ou", "seu", "sua", "meu", "minha", "este", "esta",
    "isso", "esse", "essa", "ele", "ela", "sem", "sobre", "entre", "quando",
    "the", "and", "for", "with", "from", "this", "that", "into", "não", "nao",
    "arquivo", "arquivos", "codigo", "código", "crie", "criar", "faca", "faça",
    "fazer", "adicione", "adicionar", "novo", "nova", "usando", "use",
}


def _tokens(text: str) -> set[str]:
    """Tokeniza p/ matching: minúsculas, sem acentos, sem stopwords, len>=3."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return {t for t in re.findall(r"[a-z0-9_]{3,}", text) if t not in _STOPWORDS}


class LessonMemory:
    """Memória persistente de lições do Coder, com recall lexical."""

    def __init__(self, path: str = "data/lessons.db"):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS lessons (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                task       TEXT NOT NULL,
                lesson     TEXT NOT NULL,
                kind       TEXT NOT NULL DEFAULT 'reflection',
                tokens     TEXT NOT NULL DEFAULT '',
                hits       INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._conn.commit()

    def add(self, task: str, lesson: str, kind: str = "reflection") -> int | None:
        """Registra uma lição. Dedup por conteúdo normalizado (re-aprender a
        mesma lição só conta um 'hit', não cria duplicata). Retorna o id."""
        task = (task or "").strip()[:300]
        lesson = (lesson or "").strip()[:600]
        if len(lesson) < 15:  # curta demais para ser uma lição real
            return None
        toks = _tokens(task) | _tokens(lesson)
        with self._lock:
            # Dedup exata por texto da lição (a forma mais segura).
            row = self._conn.execute(
                "SELECT id FROM lessons WHERE lesson = ?", (lesson,)
            ).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE lessons SET hits = hits + 1 WHERE id = ?", (row["id"],))
                self._conn.commit()
                return row["id"]
            cur = self._conn.execute(
                "INSERT INTO lessons (created_at, task, lesson, kind, tokens) "
                "VALUES (?, ?, ?, ?, ?)",
                (datetime.now().isoformat(timespec="seconds"), task, lesson,
                 kind, " ".join(sorted(toks))),
            )
            self._conn.commit()
            logger.info(f"[lessons] + ({kind}) {lesson[:80]}")
            return cur.lastrowid

    def relevant(self, task: str, limit: int = 4) -> list[dict]:
        """Lições mais relevantes para a tarefa — score por sobreposição de
        tokens; empates decididos por recência. Lições de regressão sempre
        pesam mais (são as mais caras de re-aprender)."""
        q = _tokens(task)
        if not q:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, task, lesson, kind, tokens FROM lessons "
                "ORDER BY id DESC LIMIT 500"
            ).fetchall()
        scored = []
        for r in rows:
            overlap = len(q & set(r["tokens"].split()))
            if overlap == 0:
                continue
            bonus = 2 if r["kind"] == "regression" else 0
            scored.append((overlap + bonus, r["id"], dict(r)))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        top = [d for _, _, d in scored[:limit]]
        if top:
            with self._lock:
                self._conn.execute(
                    f"UPDATE lessons SET hits = hits + 1 WHERE id IN "
                    f"({','.join('?' * len(top))})", [d["id"] for d in top])
                self._conn.commit()
        return top

    def recent(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, created_at, task, lesson, kind, hits FROM lessons "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM lessons").fetchone()[0]

    def delete(self, lesson_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def format_section(self, task: str, limit: int = 4) -> str:
        """Bloco pronto para o system prompt — '' quando não há lição relevante."""
        les = self.relevant(task, limit=limit)
        if not les:
            return ""
        icons = {"regression": "🛡️", "failure": "✗", "reflection": "💡"}
        lines = [f"- {icons.get(l['kind'], '•')} {l['lesson']}" for l in les]
        return (
            "\n\nLIÇÕES APRENDIDAS (da SUA experiência em tarefas anteriores — "
            "leve a sério, você já pagou o preço por elas):\n" + "\n".join(lines)
        )
