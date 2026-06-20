"""Curador de Memória do A.P.O.L.O.

Conforme ele estuda 24/7, a base acumula conhecimento repetido (o mesmo tópico
estudado de novo, ou textos quase idênticos de fontes diferentes). O curador
encontra esses grupos de duplicatas e propõe manter o melhor de cada grupo.

Seguro por design: `scan()` é só leitura (relatório). A remoção é explícita
(`apply(ids)`), disparada pelo usuário — nada é apagado automaticamente.
"""

import difflib
import logging
import re
from collections import defaultdict

logger = logging.getLogger(__name__)

CONTENT_COMPARE_CHARS = 600   # quanto do conteúdo comparar (custo do difflib)
SIM_THRESHOLD = 0.85          # ratio acima do qual 2 textos são "quase iguais"
CONTENT_SCAN_MAX = 400        # acima disso, só dedup por título (difflib O(n²) fica caro)

_TITLE_NOISE = re.compile(
    r"\[a\.p\.o\.l\.o\.\]|\[tendência\]|pesquisa profunda:|pesquisa:|\(parte \d+/\d+\)",
    re.IGNORECASE,
)


def _norm_title(title: str) -> str:
    t = _TITLE_NOISE.sub("", (title or "").lower())
    t = re.sub(r"[^0-9a-záéíóúâêôãõàç ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class MemoryCurator:
    """Encontra e remove conhecimento duplicado na base do Supabase."""

    def __init__(self, knowledge_db=None, rag=None, db=None):
        self.knowledge_db = knowledge_db
        self.rag = rag
        self.db = db

    def scan(self, sample_limit: int = 1000, sim_threshold: float = SIM_THRESHOLD) -> dict:
        """Relatório (somente leitura) dos grupos de duplicatas encontrados."""
        rows = self.knowledge_db.all_rows(sample_limit) if self.knowledge_db else []
        n = len(rows)
        if n < 2:
            return {"total": n, "duplicate_clusters": 0, "removable": 0, "clusters": []}

        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        norm = [_norm_title(r.get("title")) for r in rows]
        body = [(r.get("content") or "")[:CONTENT_COMPARE_CHARS] for r in rows]

        # 1) Título normalizado idêntico → mesmo tópico estudado mais de uma vez.
        by_title: dict[str, list[int]] = defaultdict(list)
        for i, t in enumerate(norm):
            if t:
                by_title[t].append(i)
        for idxs in by_title.values():
            for j in idxs[1:]:
                union(idxs[0], j)

        # 2) Conteúdo quase idêntico dentro da mesma categoria (pega títulos diferentes).
        # Só roda em bases pequenas — em bases grandes o difflib O(n²) custa caro e a
        # dedup por título já resolve a maioria.
        by_cat: dict[str, list[int]] = defaultdict(list)
        for i, r in enumerate(rows):
            by_cat[r.get("category") or "?"].append(i)
        for idxs in ([] if n > CONTENT_SCAN_MAX else by_cat.values()):
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    i, j = idxs[a], idxs[b]
                    if find(i) == find(j):
                        continue
                    if difflib.SequenceMatcher(None, body[i], body[j]).ratio() >= sim_threshold:
                        union(i, j)

        # Monta clusters (>1 membro). Mantém o de conteúdo mais longo.
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)

        clusters = []
        removable = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            members.sort(key=lambda i: len(rows[i].get("content") or ""), reverse=True)
            keeper, dupes = rows[members[0]], [rows[i] for i in members[1:]]
            removable += len(dupes)
            clusters.append({
                "keeper": {"id": keeper.get("id"), "title": keeper.get("title"), "url": keeper.get("url")},
                "dupes": [{"id": d.get("id"), "title": d.get("title"), "url": d.get("url")} for d in dupes],
                "count": len(members),
            })
        clusters.sort(key=lambda c: c["count"], reverse=True)

        # Trechos repetidos no índice de recall (ChromaDB) — contagem só leitura.
        chroma_duplicates = 0
        if self.rag:
            try:
                chroma_duplicates = self.rag.dedup_exact(dry_run=True)
            except Exception as e:
                logger.debug(f"[curator] chroma scan: {e}")

        # Re-estudos repetidos no log de aprendizado (SQLite) — contagem só leitura.
        log_duplicates = 0
        if self.db:
            try:
                log_duplicates = self.db.count_topic_duplicates()
            except Exception as e:
                logger.debug(f"[curator] log scan: {e}")

        return {
            "total": n,
            "duplicate_clusters": len(clusters),
            "removable": removable,
            "chroma_duplicates": chroma_duplicates,
            "log_duplicates": log_duplicates,
            "clusters": clusters,
        }

    def apply(self, ids: list) -> dict:
        """Remove duplicatas: linhas do Supabase indicadas + trechos repetidos do
        índice de recall (ChromaDB). Ação explícita do usuário."""
        ids = [i for i in (ids or []) if i is not None]
        removed = self.knowledge_db.delete_ids(ids) if (ids and self.knowledge_db) else 0
        chroma_pruned = 0
        if self.rag:
            try:
                chroma_pruned = self.rag.dedup_exact()
            except Exception as e:
                logger.warning(f"[curator] chroma prune: {e}")
        log_pruned = 0
        if self.db:
            try:
                log_pruned = self.db.dedup_learned_topics()
            except Exception as e:
                logger.warning(f"[curator] log prune: {e}")
        logger.info(f"[curator] removidas {removed} (base) + {chroma_pruned} (recall) + {log_pruned} (log)")
        return {"ok": True, "removed": removed, "chroma_pruned": chroma_pruned, "log_pruned": log_pruned}
