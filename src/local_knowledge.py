"""Base de conhecimento local — alternativa 100% offline ao Supabase.

Usa SQLite3 com FTS5 (busca de texto completo embutida no Python padrão).
Implementa a mesma interface de SupabaseKnowledge — duck typing puro,
troca transparente em app.py sem alterar nenhum chamador.

Ativado automaticamente quando SUPABASE_URL/KEY não estão configurados.
Path padrão: data/local_knowledge.db (configurável via LOCAL_KNOWLEDGE_PATH).
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from src.cache import TTLCache
from src.rerank import rerank

logger = logging.getLogger(__name__)

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS knowledge (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    url         TEXT    UNIQUE NOT NULL,
    content     TEXT,
    category    TEXT    DEFAULT 'web',
    tags        TEXT    DEFAULT '[]',
    updated_at  TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    title, content,
    content='knowledge',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS kn_ai AFTER INSERT ON knowledge BEGIN
    INSERT INTO knowledge_fts(rowid, title, content)
    VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS kn_au AFTER UPDATE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content)
    VALUES('delete', old.id, old.title, old.content);
    INSERT INTO knowledge_fts(rowid, title, content)
    VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS kn_ad AFTER DELETE ON knowledge BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content)
    VALUES('delete', old.id, old.title, old.content);
END;
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recency_score(updated_at: str | None, half_life_days: float = 90.0) -> float:
    if not updated_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        return float(0.5 ** (max(0.0, age_days) / half_life_days))
    except Exception:
        return 0.0


def _domain_of(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = (parsed.netloc or parsed.path).lower().lstrip("/")
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split("/")[0]
    except Exception:
        return ""


class LocalKnowledge:
    """Base de conhecimento local via SQLite FTS5.

    Interface idêntica a SupabaseKnowledge — pode substituí-la sem alteração
    dos chamadores. Thread-safe com WAL mode e lock de escrita.
    """

    def __init__(self, path: str = "data/local_knowledge.db"):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self._path), check_same_thread=False, timeout=10.0
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Telemetria de save (compatibilidade com SupabaseKnowledge)
        self.saved_ok = 0
        self.save_errors = 0
        self.last_error = ""
        self.last_saved_at = ""
        # Cache do painel 'Mente' — agrega muitas linhas
        self._insights = TTLCache(ttl=120.0)
        logger.info(f"LocalKnowledge ativo em {self._path}")

    def breaker_state(self) -> dict:
        return {"state": "closed", "name": "local_sqlite", "failures": 0}

    def save(
        self,
        title: str,
        url: str,
        content: str,
        category: str = "web",
        tags: list[str] | None = None,
    ) -> None:
        payload = {
            "title": (title or "")[:200],
            "url": url or "",
            "content": (content or "")[:8000],
            "category": category or "web",
            "tags": json.dumps(tags or []),
            "updated_at": _now_iso(),
        }
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO knowledge (title, url, content, category, tags, updated_at)
                       VALUES (:title, :url, :content, :category, :tags, :updated_at)
                       ON CONFLICT(url) DO UPDATE SET
                           title=excluded.title, content=excluded.content,
                           category=excluded.category, tags=excluded.tags,
                           updated_at=excluded.updated_at""",
                    payload,
                )
                self._conn.commit()
            self.saved_ok += 1
            self.last_saved_at = payload["updated_at"]
            self._insights.invalidate()
            logger.info(f"[local_kb] salvo: {title[:60]}")
        except Exception as e:
            self.save_errors += 1
            self.last_error = str(e)[:200]
            logger.warning(f"[local_kb] save error: {e}")

    def search(self, query: str, limit: int = 3) -> list[dict]:
        """FTS5 MATCH com rerank híbrido (lexical + recência)."""
        fetch_k = max(limit * 4, limit)
        rows: list[dict] = []
        try:
            # Sanitiza query para FTS5 (aspas simples → escape, caracteres especiais)
            safe_q = query.replace('"', '""').strip()
            cur = self._conn.execute(
                """SELECT k.id, k.title, k.url, k.content, k.category, k.updated_at
                   FROM knowledge k
                   JOIN knowledge_fts f ON k.id = f.rowid
                   WHERE knowledge_fts MATCH ?
                   ORDER BY f.rank
                   LIMIT ?""",
                (f'"{safe_q}"', fetch_k),
            )
            rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            # Fallback: LIKE em caso de query FTS inválida
            try:
                word = (query.split() or [query])[0][:50]
                cur = self._conn.execute(
                    """SELECT id, title, url, content, category, updated_at
                       FROM knowledge
                       WHERE title LIKE ? OR content LIKE ?
                       LIMIT ?""",
                    (f"%{word}%", f"%{word}%", fetch_k),
                )
                rows = [dict(r) for r in cur.fetchall()]
            except Exception as e2:
                logger.warning(f"[local_kb] search fallback error: {e2}")
                return []
        # Rerank híbrido igual ao Supabase
        if not rows:
            return rows
        items = [{**r, "snippet": (r.get("content") or "")[:600],
                  "recency": _recency_score(r.get("updated_at"))} for r in rows]
        ranked = rerank(query, items, limit, w_vector=0.5, w_lexical=0.3, w_recency=0.2)
        out = []
        for c in ranked:
            for aux in ("snippet", "score", "recency"):
                c.pop(aux, None)
            out.append(c)
        return out

    def format_context(self, query: str) -> str:
        results = self.search(query)
        if not results:
            return ""
        parts = [
            f"**{r['title']}** [{r['category']}]\n{(r.get('content') or '')[:500]}"
            for r in results
        ]
        return "\n\n---\n\n".join(parts)

    def stats(self) -> dict:
        try:
            row = self._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()
            total = row[0] if row else 0
        except Exception as e:
            self.last_error = str(e)[:200]
            total = 0
        return {
            "total": total,
            "saved_session": self.saved_ok,
            "save_errors": self.save_errors,
            "last_saved_at": self.last_saved_at,
            "last_error": self.last_error,
        }

    def all_rows(self, limit: int = 1000) -> list[dict]:
        try:
            cur = self._conn.execute(
                "SELECT id,title,url,content,category,updated_at FROM knowledge "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            logger.warning(f"[local_kb] all_rows: {e}")
            return []

    def delete_by_url(self, url: str) -> int:
        if not url:
            return 0
        try:
            with self._lock:
                self._conn.execute("DELETE FROM knowledge WHERE url = ?", (url,))
                self._conn.commit()
            return 1
        except Exception as e:
            logger.warning(f"[local_kb] delete_by_url: {e}")
            return 0

    def delete_ids(self, ids: list) -> int:
        if not ids:
            return 0
        try:
            placeholders = ",".join("?" * len(ids))
            with self._lock:
                self._conn.execute(
                    f"DELETE FROM knowledge WHERE id IN ({placeholders})", ids
                )
                self._conn.commit()
            return len(ids)
        except Exception as e:
            logger.warning(f"[local_kb] delete_ids: {e}")
            return 0

    def scan_junk(self, limit: int = 1000) -> list[dict]:
        """Faxina: itens da base que NÃO passariam na higiene de ingestão (lixo/spam/
        injeção que entrou antes do porteiro). Só leitura; o usuário purga por id."""
        from src.content_hygiene import scan_rows
        return scan_rows(self.all_rows(limit))

    def insights(self, sample_limit: int = 1000) -> dict:
        """Agrega categorias/setores/domínios — alimenta o painel Mente."""
        cached = self._insights.get()
        if cached is not None:
            return cached
        empty = {"total": 0, "sampled": False,
                 "categories": [], "sectors": [], "domains": [], "recent": []}
        try:
            cur = self._conn.execute(
                "SELECT title,url,category,tags,updated_at FROM knowledge "
                "ORDER BY updated_at DESC LIMIT ?",
                (sample_limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
            total_row = self._conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()
            total = total_row[0] if total_row else len(rows)
        except Exception as e:
            logger.warning(f"[local_kb] insights: {e}")
            return self._insights.peek() or empty

        from src.topics import classify_sector, ALL_SECTORS
        known_sectors = set(ALL_SECTORS.keys())

        cat_counts: dict[str, int] = {}
        sec_counts: dict[str, int] = {}
        dom_counts: dict[str, int] = {}
        for r in rows:
            cat = (r.get("category") or "outros").strip() or "outros"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            # Síntese cross-domain fica de fora da contagem por setor (ver knowledge.py::insights).
            if cat != "synthesis":
                tags = json.loads(r.get("tags") or "[]") if isinstance(r.get("tags"), str) else []
                sector = tags[0] if (tags and tags[0] in known_sectors) else classify_sector(r.get("title") or "")
                sec_counts[sector] = sec_counts.get(sector, 0) + 1
            dom = _domain_of(r.get("url") or "")
            if dom:
                dom_counts[dom] = dom_counts.get(dom, 0) + 1

        result = {
            "total": total,
            "sampled": len(rows) >= sample_limit and total > len(rows),
            "categories": sorted([{"name": k, "count": v} for k, v in cat_counts.items()],
                                  key=lambda x: x["count"], reverse=True),
            "sectors": sorted([{"name": k, "count": v} for k, v in sec_counts.items()],
                              key=lambda x: x["count"], reverse=True),
            "domains": sorted([{"name": k, "count": v} for k, v in dom_counts.items()],
                              key=lambda x: x["count"], reverse=True)[:8],
            "recent": [{"title": (r.get("title") or "—")[:120],
                        "category": r.get("category") or "outros",
                        "url": r.get("url") or "",
                        "updated_at": r.get("updated_at")}
                       for r in rows[:12]],
        }
        return self._insights.set(result)
