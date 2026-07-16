"""RAG local com ChromaDB para contexto de exemplos."""

import logging
from datetime import datetime, timezone
from pathlib import Path
import chromadb

from src.cache import TTLCache

logger = logging.getLogger(__name__)

COLLECTION_NAME = "apolo_examples"

_RECALL_HALF_LIFE_DAYS = 90.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _recency_from_iso(value: str | None) -> float:
    """Decaimento exponencial por idade (meia-vida 90d). Sem data → 0 (sem bônus)."""
    if not value:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        return float(0.5 ** (max(0.0, age_days) / _RECALL_HALF_LIFE_DAYS))
    except Exception:
        return 0.0


def _make_embed_fn(model: str | None):
    """Cria a embedding function para o ChromaDB.

    Se EMBED_MODEL estiver configurado (ex.: 'nomic-embed-text'), usa Ollama para
    gerar embeddings locais — melhor qualidade para PT-BR. Requer:
      ollama pull nomic-embed-text
    Sem EMBED_MODEL, usa a default do chromadb (all-MiniLM-L6-v2).

    Quando o modelo de embed muda, a coleção usa um nome diferente para evitar
    incompatibilidade de dimensões entre embeddings antigos e novos.
    """
    if not model:
        return None  # usa o default do ChromaDB
    # Fallback soberano 100% Python (M11 11.1): sem ONNX, sem Ollama, sem internet.
    if model == "hashing":
        from src.embeddings import HashingEmbeddingFunction
        logger.info("[rag] embeddings locais via fallback Python (apolo-hashing)")
        return HashingEmbeddingFunction()
    try:
        from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
        ef = OllamaEmbeddingFunction(
            url="http://localhost:11434",
            model_name=model,
        )
        logger.info(f"[rag] embeddings locais via Ollama: {model}")
        return ef
    except Exception as e:
        logger.warning(f"[rag] não consegui carregar embedding Ollama ({model}): {e} — usando default")
        return None


class RAGManager:
    def __init__(
        self,
        chroma_path: str = "./data/chroma_db",
        examples_path: str = "./data/examples",
        embed_model: str | None = None,
    ):
        self.examples_path = Path(examples_path)
        self.client = chromadb.PersistentClient(path=chroma_path)
        # Nome da coleção inclui o modelo de embedding para evitar incompatibilidade
        # de dimensões quando o modelo muda (antigo: cosine/384d, nomic: cosine/768d).
        _suffix = f"_{embed_model.replace(':', '_').replace('-', '_')}" if embed_model else ""
        _coll_name = f"{COLLECTION_NAME}{_suffix}"
        _embed_fn = _make_embed_fn(embed_model)
        kwargs: dict = {"name": _coll_name, "metadata": {"hnsw:space": "cosine"}}
        if _embed_fn:
            kwargs["embedding_function"] = _embed_fn
        self.collection = self.client.get_or_create_collection(**kwargs)
        # Cache da métrica de qualidade do recall (painel Saúde): cada cálculo faz
        # ~6 embeddings via Ollama. Métrica muda devagar → TTL curto basta.
        self._rq_cache = TTLCache(ttl=90.0)
        self._load_examples()

    def _load_examples(self) -> None:
        if not self.examples_path.exists():
            logger.warning(f"Pasta de exemplos não encontrada: {self.examples_path}")
            return

        loaded = 0
        for file in self.examples_path.glob("**/*"):
            if file.suffix not in {".py", ".txt", ".md"}:
                continue
            doc_id = str(file.relative_to(self.examples_path))
            if self.collection.get(ids=[doc_id])["ids"]:
                continue
            try:
                content = file.read_text(encoding="utf-8")
                self.collection.add(
                    documents=[content],
                    ids=[doc_id],
                    metadatas=[{"source": doc_id}],
                )
                loaded += 1
            except Exception as e:
                logger.warning(f"Erro ao carregar {file}: {e}")

        if loaded:
            logger.info(f"RAG: {loaded} novos exemplos indexados")

    def get_context(self, query: str, n_results: int = 3) -> str:
        count = self.collection.count()
        if count == 0:
            return "Nenhum exemplo disponível."

        results = self.collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )
        docs = results.get("documents", [[]])[0]
        return "\n\n---\n\n".join(docs) if docs else "Nenhum exemplo relevante encontrado."

    def recall(self, query: str, n_results: int = 4) -> list[dict]:
        """Recuperação semântica com RERANK híbrido — busca um conjunto maior de
        candidatos no índice vetorial e os reordena combinando similaridade de
        embedding (fraca no modelo local) com sobreposição lexical com a consulta,
        cortando quase-duplicatas. Base do chat, do agente e da Pesquisa Profunda."""
        count = self.collection.count()
        if count == 0:
            return []
        # Busca mais candidatos do que o necessário para dar material ao reranker.
        fetch_k = min(count, max(n_results * 4, n_results))
        try:
            res = self.collection.query(
                query_texts=[query], n_results=fetch_k,
                include=["documents", "distances", "metadatas"],
            )
        except Exception as e:
            logger.warning(f"recall error: {e}")
            return []

        docs  = res.get("documents", [[]])[0]
        dists = res.get("distances", [[]])[0] or [None] * len(docs)
        metas = (res.get("metadatas") or [[]])[0] or [None] * len(docs)
        candidates: list[dict] = []
        for doc, dist, meta in zip(docs, dists, metas):
            title, source, body = _parse_learned_doc(doc)
            relevance = round(1 - dist, 3) if isinstance(dist, (int, float)) else None
            studied_at = (meta or {}).get("studied_at") if isinstance(meta, dict) else None
            verified = (meta or {}).get("verified") if isinstance(meta, dict) else None
            candidates.append({
                "title": title,
                "source": source,
                "snippet": body[:600],
                "relevance": relevance,
                "recency": _recency_from_iso(studied_at),
                "verified": verified,
            })
        # Recência leve (memória recém-estudada pesa um pouco mais); docs antigos sem
        # metadado simplesmente não recebem o bônus (recency=0). P2.1: fidelidade à
        # fonte também pesa um pouco — "failed" penaliza, "verified" bonifica de leve,
        # "unchecked"/ausente (maioria, só ~10% é amostrado) fica neutro.
        return _rerank(query, candidates, n_results, w_recency=0.15, w_verified=0.08)

    def recall_quality(self, sample_queries: list[str]) -> dict:
        """Mede a saúde do recall: para cada consulta de amostra, pega o melhor
        resultado e mede similaridade vetorial e sobreposição lexical médias.
        Valores altos = o índice recupera bem; baixos = embedding/índice degradado."""
        from src.rerank import lexical_overlap, tokenize
        cached = self._rq_cache.get()
        if cached is not None:
            return cached
        count = self.collection.count()
        out = {"index_docs": count, "samples": 0, "avg_relevance": None,
               "avg_lexical": None, "avg_score": None}
        if count == 0 or not sample_queries:
            return out
        rels, lexs, scores = [], [], []
        for q in sample_queries:
            hits = self.recall(q, 1)
            if not hits:
                continue
            h = hits[0]
            if isinstance(h.get("relevance"), (int, float)):
                rels.append(h["relevance"])
            lexs.append(lexical_overlap(tokenize(q), f"{h.get('title','')} {h.get('snippet','')}"))
            if isinstance(h.get("score"), (int, float)):
                scores.append(h["score"])
        n = max(1, len(lexs))
        out["samples"] = len(lexs)
        out["avg_relevance"] = round(sum(rels) / len(rels), 3) if rels else None
        out["avg_lexical"] = round(sum(lexs) / n, 3)
        out["avg_score"] = round(sum(scores) / len(scores), 3) if scores else None
        return self._rq_cache.set(out)

    def add_example(self, content: str, doc_id: str, metadata: dict | None = None) -> None:
        # Carimba a data — alimenta o boost de recência do recall (memória fresca).
        meta = {"source": doc_id, "studied_at": _now_iso()}
        if metadata:
            meta.update(metadata)
        self.collection.upsert(
            documents=[content],
            ids=[doc_id],
            metadatas=[meta],
        )
        self._rq_cache.invalidate()  # índice mudou → recalcula a qualidade na próxima
        try:
            from src.query_cache import invalidate_all as _qinv
            _qinv()   # #1 #2 índice mudou → queries em cache podem retornar stale
        except Exception:
            pass
        logger.info(f"Exemplo adicionado: {doc_id}")

    def add_chunked(
        self,
        content: str,
        doc_id: str,
        metadata: dict | None = None,
        chunk_size: int = 1200,
        overlap: int = 200,
    ) -> int:
        """Indexa um documento grande em chunks com overlap para melhor recall.
        Documentos curtos (≤ chunk_size) são indexados como um único item.
        Retorna o número de chunks criados."""
        if len(content) <= chunk_size:
            self.add_example(content, doc_id, metadata)
            return 1
        chunks: list[str] = []
        start = 0
        while start < len(content):
            end = min(start + chunk_size, len(content))
            chunks.append(content[start:end])
            if end == len(content):
                break
            start += chunk_size - overlap
        for i, chunk in enumerate(chunks):
            self.add_example(chunk, f"{doc_id}_c{i}", metadata)
        return len(chunks)

    def forget_topic(self, topic: str) -> int:
        """Remove do índice de recall os documentos de um tópico (1ª linha '# {topic}').
        Usado pelo 'esquecer' manual — garante que o conhecimento não volte no recall."""
        target = f"# {(topic or '').strip()}".lower()
        if not topic:
            return 0
        try:
            data = self.collection.get(include=["documents"])
        except Exception as e:
            logger.warning(f"forget_topic get: {e}")
            return 0
        ids = data.get("ids", []) or []
        docs = data.get("documents", []) or []
        to_del = [i for i, d in zip(ids, docs)
                  if (d or "").strip().lower().startswith(target)]
        if to_del:
            try:
                self.collection.delete(ids=to_del)
            except Exception as e:
                logger.warning(f"forget_topic delete: {e}")
                return 0
        return len(to_del)

    def dedup_exact(self, dry_run: bool = False) -> int:
        """Remove documentos de conteúdo idêntico do índice de recall, mantendo um
        de cada. Usado pelo Curador de Memória. `dry_run=True` só conta. Seguro:
        compara conteúdo exato (normalizado), não similaridade aproximada."""
        try:
            data = self.collection.get(include=["documents"])
        except Exception as e:
            logger.warning(f"dedup_exact get: {e}")
            return 0
        ids = data.get("ids", []) or []
        docs = data.get("documents", []) or []
        seen: set[str] = set()
        to_delete: list[str] = []
        for doc_id, doc in zip(ids, docs):
            key = (doc or "").strip()
            if key in seen:
                to_delete.append(doc_id)
            else:
                seen.add(key)
        if to_delete and not dry_run:
            try:
                self.collection.delete(ids=to_delete)
                logger.info(f"[rag] dedup_exact removeu {len(to_delete)} docs duplicados")
            except Exception as e:
                logger.warning(f"dedup_exact delete: {e}")
                return 0
        return len(to_delete)


# Reranker compartilhado (também usado pela base Supabase). Re-exportado com os
# nomes "privados" históricos para manter compatibilidade de imports/testes.
# F401: são RE-EXPORTS (usados por tests/test_rerank.py) — nunca remover.
from src.rerank import tokenize as _tokenize          # noqa: E402,F401
from src.rerank import lexical_overlap as _lexical_overlap  # noqa: E402,F401
from src.rerank import rerank as _rerank              # noqa: E402,F401


def _parse_learned_doc(doc: str) -> tuple[str, str, str]:
    """Extrai (título, fonte, corpo) de um doc no formato '# {topic}\\nFonte: {url}\\n\\n{body}'."""
    title, source, body = "", "", doc
    lines = doc.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip()
        rest = lines[1:]
        if rest and rest[0].lower().startswith("fonte:"):
            source = rest[0].split(":", 1)[1].strip()
            rest = rest[1:]
        body = "\n".join(rest).strip()
    return title, source, body
