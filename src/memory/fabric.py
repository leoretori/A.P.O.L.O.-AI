"""MemoryFabric — a porta única para toda a memória do A.P.O.L.O. (Épico 2.1).

Antes a memória estava espalhada: RAG (ChromaDB, semântica), base de conhecimento
(FTS/Supabase, artigos estudados) e lições do Coder. Cada call-site tinha de saber
QUAL memória consultar e como. O MemoryFabric unifica isso atrás de dois verbos:

    remember(text, kind, tags=...)   → grava na memória certa
    recall(query, kind=None)         → recupera (de uma ou de todas), num formato único

`kind` decide o backend:
    "semantic"   → RAG (ChromaDB) — conhecimento/exemplos recuperáveis por significado
    "knowledge"  → base de conhecimento (FTS local ou Supabase) — artigos estudados
    "lesson"     → LessonMemory — lições que o Coder aprendeu

É uma FACHADA fina: não duplica armazenamento, só orquestra os singletons já
existentes (injetados no construtor). Backends ausentes (None) são ignorados com
segurança, então funciona mesmo com Supabase desligado ou sem lições.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("apolo.memory")

# Tipos de memória que o fabric conhece. A ordem define a prioridade no recall
# unificado (semântica primeiro, depois base, depois lições).
KINDS = ("semantic", "knowledge", "lesson")


@dataclass
class MemoryHit:
    """Um resultado de recall, normalizado — independente de qual memória veio."""
    kind: str
    title: str
    text: str
    source: str = ""
    score: float | None = None
    when: str | None = None            # ISO datetime, quando aplicável
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "title": self.title, "text": self.text,
            "source": self.source, "score": self.score, "when": self.when,
            "tags": self.tags,
        }


def _doc_id(source: str, text: str) -> str:
    """Id estável para a memória semântica: usa a fonte se houver, senão um hash
    do conteúdo (evita duplicar o mesmo texto no índice)."""
    if source:
        return source
    return "mem_" + hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:16]


class MemoryFabric:
    def __init__(self, rag=None, knowledge=None, lessons=None):
        self.rag = rag
        self.knowledge = knowledge
        self.lessons = lessons

    # ── Escrita ───────────────────────────────────────────────
    def remember(self, text: str, kind: str = "semantic", *,
                 title: str = "", source: str = "", tags: list[str] | None = None,
                 task: str = "", metadata: dict | None = None) -> bool:
        """Grava uma memória. Retorna True se algo foi de fato persistido.
        - semantic  → RAG.add_example (title/tags viram metadados)
        - knowledge → knowledge.save (title/source/tags/category)
        - lesson    → lessons.add (task = contexto, text = a lição)
        """
        text = (text or "").strip()
        if not text or kind not in KINDS:
            return False
        try:
            if kind == "semantic":
                if not self.rag:
                    return False
                meta = {"title": title} if title else {}
                if tags:
                    meta["tags"] = ",".join(tags)
                if metadata:
                    meta.update(metadata)
                self.rag.add_example(text, _doc_id(source, text), meta or None)
                return True
            if kind == "knowledge":
                if not self.knowledge:
                    return False
                self.knowledge.save(title=title or text[:60], url=source,
                                    content=text, category=(metadata or {}).get("category", "web"),
                                    tags=tags or [])
                return True
            if kind == "lesson":
                if not self.lessons:
                    return False
                return self.lessons.add(task=task or title, lesson=text,
                                        kind=(metadata or {}).get("kind", "reflection")) is not None
        except Exception as e:
            logger.warning(f"remember({kind}) falhou: {e}")
        return False

    # ── Leitura ───────────────────────────────────────────────
    def recall(self, query: str, kind: str | None = None, limit: int = 4) -> list[MemoryHit]:
        """Recupera memórias relevantes num formato único (MemoryHit).
        `kind=None` consulta TODAS as memórias disponíveis e devolve até `limit`
        de cada uma (a porta única). `kind` específico consulta só aquela."""
        query = (query or "").strip()
        if not query:
            return []
        kinds = [kind] if kind else list(KINDS)
        hits: list[MemoryHit] = []
        for k in kinds:
            try:
                hits.extend(self._recall_one(query, k, limit))
            except Exception as e:
                logger.warning(f"recall({k}) falhou: {e}")
        return hits

    def _recall_one(self, query: str, kind: str, limit: int) -> list[MemoryHit]:
        if kind == "semantic" and self.rag:
            return [MemoryHit(
                kind="semantic", title=h.get("title", ""),
                text=h.get("snippet", ""), source=h.get("source", ""),
                score=h.get("relevance"),
            ) for h in self.rag.recall(query, limit)]
        if kind == "knowledge" and self.knowledge:
            return [MemoryHit(
                kind="knowledge", title=h.get("title", ""),
                text=(h.get("content") or "")[:600], source=h.get("url", ""),
                when=h.get("updated_at"), tags=_split_tags(h.get("tags")),
            ) for h in self.knowledge.search(query, limit)]
        if kind == "lesson" and self.lessons:
            return [MemoryHit(
                kind="lesson", title=h.get("task", "") or "lição",
                text=h.get("lesson", ""), when=h.get("created_at"),
                tags=[h.get("kind")] if h.get("kind") else [],
            ) for h in self.lessons.relevant(query, limit)]
        return []

    def recall_text(self, query: str, kind: str | None = None, limit: int = 4) -> str:
        """Bloco de contexto pronto para injetar num prompt (Markdown enxuto)."""
        hits = self.recall(query, kind, limit)
        if not hits:
            return ""
        icon = {"semantic": "🧠", "knowledge": "📚", "lesson": "🎓"}
        return "\n".join(
            f"{icon.get(h.kind, '•')} **{h.title}** — {h.text[:280]}".rstrip()
            for h in hits
        )

    def stats(self) -> dict:
        """Quais memórias estão conectadas (para observabilidade)."""
        return {
            "semantic": self.rag is not None,
            "knowledge": self.knowledge is not None,
            "lesson": self.lessons is not None,
        }


def _split_tags(raw) -> list[str]:
    """Normaliza tags que podem vir como lista, JSON ou string separada por vírgula."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t) for t in raw]
    if isinstance(raw, str):
        s = raw.strip()
        if s.startswith("["):
            try:
                import json
                return [str(t) for t in json.loads(s)]
            except Exception:
                pass
        return [t.strip() for t in s.split(",") if t.strip()]
    return []
