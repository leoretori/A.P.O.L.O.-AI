"""Base de conhecimento persistente no Supabase."""

import logging
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.cache import TTLCache
from src.rerank import rerank
from src.resilience import CircuitBreaker, CircuitOpenError, retry_call

logger = logging.getLogger(__name__)


def _recency_score(updated_at: str | None, half_life_days: float = 90.0) -> float:
    """Decaimento exponencial por idade: recém-atualizado → ~1, antigo → ~0."""
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


def _rerank_rows(query: str, rows: list[dict], limit: int) -> list[dict]:
    """Aplica o rerank híbrido a linhas do Supabase. FTS não dá score vetorial, então
    usa lexical + recência (conhecimento recém-estudado pesa um pouco mais) + dedup.
    Devolve as linhas originais (sem campos auxiliares) reordenadas."""
    if not rows:
        return []
    items = [{**r, "snippet": (r.get("content") or "")[:600],
              "recency": _recency_score(r.get("updated_at"))} for r in rows]
    ranked = rerank(query, items, limit, w_vector=0.5, w_lexical=0.3, w_recency=0.2)
    out = []
    for c in ranked:
        for aux in ("snippet", "score", "recency"):
            c.pop(aux, None)
        out.append(c)
    return out


def _domain_of(url: str) -> str:
    """Extrai o domínio de uma URL (sem www). URLs internas (research://) viram a fonte."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path  # research://apolo/... cai no path
        netloc = netloc.lower().lstrip("/")
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc.split("/")[0]
    except Exception:
        return ""


class SupabaseKnowledge:
    def __init__(self, url: str, key: str):
        from supabase import create_client
        # Timeout EXPLÍCITO no cliente: sem ele, o default (120 s) × retry (3×) deixa
        # uma escrita travada segurando uma thread do pool compartilhado por até ~6 min.
        # Como o summarizer do learner usa o MESMO pool (asyncio.to_thread), escritas
        # penduradas em rede ruim ESGOTAM o pool e CONGELAM o aprendizado (bug real:
        # "estudou 45 e travou"). O circuit breaker não protegia disso — ele só conta
        # exceções, não pendências. Com timeout curto, a chamada falha rápido → o breaker
        # abre → rejeição imediata; nada segura thread. Ajustável via SUPABASE_TIMEOUT.
        timeout = int(os.getenv("SUPABASE_TIMEOUT", "15"))
        try:
            from supabase import ClientOptions
            self.client = create_client(url, key, options=ClientOptions(
                postgrest_client_timeout=timeout,
                storage_client_timeout=timeout,
            ))
        except Exception:
            # Versão antiga sem ClientOptions — segue sem timeout explícito.
            self.client = create_client(url, key)
        # Telemetria de upload — para saber se o conhecimento está subindo de verdade.
        self.saved_ok = 0
        self.save_errors = 0
        self.last_error = ""
        self.last_saved_at = ""
        # Cache do painel 'Mente' — a agregação varre ~1000 linhas e é cara.
        # Invalida ao salvar; senão expira por TTL.
        self._insights = TTLCache(ttl=120.0)
        # Circuit breaker: se o Supabase cair, para de martelar (rejeita rápido)
        # por 30 s e depois testa de novo — evita travar o aprendizado em rede ruim.
        self._breaker = CircuitBreaker(fail_max=5, reset_after=30.0, name="supabase")
        logger.info("Supabase knowledge DB conectado")

    def _execute(self, build):
        """Roda uma operação Supabase com retry (falhas transitórias de rede) sob
        o circuit breaker. `build` é uma função sem args que faz a chamada."""
        return self._breaker.call(retry_call, build, attempts=3, base_delay=0.4)

    def breaker_state(self) -> dict:
        return self._breaker.snapshot()

    def save(
        self,
        title: str,
        url: str,
        content: str,
        category: str = "web",
        tags: list[str] | None = None,
    ) -> None:
        payload = {
            "title": title[:200],
            "url": url,
            "content": content[:8000],
            "category": category,
            "tags": tags or [],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            # Retry com backoff: uma falha transitória de rede não deve descartar
            # conhecimento aprendido (antes ia direto para save_errors e era perdido).
            self._execute(lambda: self.client.table("knowledge")
                          .upsert(payload, on_conflict="url").execute())
            self.saved_ok += 1
            self.last_saved_at = datetime.now(timezone.utc).isoformat()
            self._insights.invalidate()  # base mudou → invalida o painel Mente
            logger.info(f"Knowledge salvo: {title[:60]}")
        except CircuitOpenError as e:
            self.save_errors += 1
            self.last_error = "Supabase indisponível (circuito aberto)"
            logger.warning(f"Supabase save pulado: {e}")
        except Exception as e:
            self.save_errors += 1
            self.last_error = str(e)[:200]
            logger.warning(f"Supabase save error (após retries): {e}")

    def search(self, query: str, limit: int = 3) -> list[dict]:
        # Busca mais candidatos do que o necessário e reordena com o rerank híbrido
        # (lexical + dedup), igual à memória semântica — o FTS sozinho ordena mal.
        fetch_k = max(limit * 4, limit)
        rows: list[dict] = []
        try:
            resp = (
                self.client.table("knowledge")
                .select("title, url, content, category, updated_at")
                .text_search("fts", query)
                .limit(fetch_k)
                .execute()
            )
            rows = resp.data or []
        except Exception as e:
            logger.debug(f"FTS error, tentando ilike: {e}")
            try:
                word = query.split()[0] if query.split() else query
                resp = (
                    self.client.table("knowledge")
                    .select("title, url, content, category, updated_at")
                    .ilike("content", f"%{word}%")
                    .limit(fetch_k)
                    .execute()
                )
                rows = resp.data or []
            except Exception as e2:
                logger.warning(f"Supabase search error: {e2}")
                return []
        return _rerank_rows(query, rows, limit)

    def format_context(self, query: str) -> str:
        results = self.search(query)
        if not results:
            return ""
        parts = [
            f"**{r['title']}** [{r['category']}]\n{r['content'][:500]}"
            for r in results
        ]
        return "\n\n---\n\n".join(parts)

    def stats(self) -> dict:
        try:
            # count="exact" vem no cabeçalho; limit(1) evita baixar todas as linhas.
            resp = self._execute(lambda: self.client.table("knowledge")
                                 .select("id", count="exact").limit(1).execute())
            total = resp.count or 0
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
        """Linhas com conteúdo — usado pelo Curador de Memória."""
        try:
            resp = (
                self.client.table("knowledge")
                .select("id,title,url,content,category,updated_at")
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.warning(f"all_rows error: {e}")
            return []

    def delete_by_url(self, url: str) -> int:
        """Remove linhas pela URL (usado pelo 'esquecer' manual)."""
        if not url:
            return 0
        try:
            self.client.table("knowledge").delete().eq("url", url).execute()
            return 1
        except Exception as e:
            logger.warning(f"delete_by_url error: {e}")
            return 0

    def delete_ids(self, ids: list) -> int:
        """Remove linhas por id (usado pelo Curador). Retorna quantas pediu remover."""
        if not ids:
            return 0
        try:
            self.client.table("knowledge").delete().in_("id", ids).execute()
            return len(ids)
        except Exception as e:
            logger.warning(f"delete_ids error: {e}")
            return 0

    def scan_junk(self, limit: int = 1000) -> list[dict]:
        """Relatório (só leitura) de itens da base que NÃO passariam na higiene de
        ingestão — lixo/spam/injeção que entrou ANTES do porteiro existir (ex.: a
        página "responda apenas: ok"). O usuário decide o que remover (purga por id
        via delete_ids). Ver src/content_hygiene."""
        from src.content_hygiene import scan_rows
        return scan_rows(self.all_rows(limit))

    def insights(self, sample_limit: int = 1000) -> dict:
        """Visão agregada da base — alimenta o painel 'Mente do A.P.O.L.O.'.

        Conta o total exato e agrega categorias/domínios/recentes sobre as
        linhas mais recentes (até `sample_limit`).

        Cacheado por TTL (invalidado a cada save) — a agregação varre muitas
        linhas e o painel 'Mente' chamava isso a cada abertura."""
        cached = self._insights.get()
        if cached is not None:
            return cached
        empty = {"total": 0, "sampled": False, "categories": [], "sectors": [], "domains": [], "recent": []}
        try:
            resp = self._execute(lambda: (
                self.client.table("knowledge")
                .select("title,url,category,tags,updated_at", count="exact")
                .order("updated_at", desc=True)
                .limit(sample_limit)
                .execute()
            ))
            rows = resp.data or []
            total = resp.count if resp.count is not None else len(rows)
        except Exception as e:
            logger.warning(f"insights error: {e}")
            # Em falha, devolve o último cache (mesmo expirado) se houver — melhor
            # que um painel vazio durante uma queda transitória do Supabase.
            return self._insights.peek() or empty

        # Classificador de setor importado de forma preguiçosa (evita ciclo de import).
        from src.topics import classify_sector, ALL_SECTORS
        known_sectors = set(ALL_SECTORS.keys())

        cat_counts: dict[str, int] = {}
        sec_counts: dict[str, int] = {}
        dom_counts: dict[str, int] = {}
        for r in rows:
            cat = (r.get("category") or "outros").strip() or "outros"
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

            # Setor: usa a tag persistida (se for um setor válido); senão classifica pelo título.
            tags = r.get("tags") or []
            sector = tags[0] if (tags and tags[0] in known_sectors) else classify_sector(r.get("title") or "")
            sec_counts[sector] = sec_counts.get(sector, 0) + 1

            dom = _domain_of(r.get("url") or "")
            if dom:
                dom_counts[dom] = dom_counts.get(dom, 0) + 1

        categories = sorted(
            [{"name": k, "count": v} for k, v in cat_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )
        sectors = sorted(
            [{"name": k, "count": v} for k, v in sec_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )
        domains = sorted(
            [{"name": k, "count": v} for k, v in dom_counts.items()],
            key=lambda x: x["count"], reverse=True,
        )[:8]
        recent = [
            {
                "title": (r.get("title") or "—")[:120],
                "category": (r.get("category") or "outros"),
                "url": r.get("url") or "",
                "updated_at": r.get("updated_at"),
            }
            for r in rows[:12]
        ]
        result = {
            "total": total,
            "sampled": len(rows) >= sample_limit and total > len(rows),
            "categories": categories,
            "sectors": sectors,
            "domains": domains,
            "recent": recent,
        }
        return self._insights.set(result)
