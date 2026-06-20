"""
Modo Pesquisa Profunda — agente de raciocínio multi-etapas do A.P.O.L.O.

Para perguntas complexas, em vez de uma única passada do LLM:
  1. PLANEJA  → decompõe a pergunta em sub-perguntas investigativas
  2. PESQUISA → para cada frente, recupera o que já aprendeu (RAG semântico) + busca na web, em paralelo
  3. SINTETIZA → funde todas as evidências numa resposta única, técnica e CITADA

O raciocínio é transmitido ao vivo (eventos 'step') para que o usuário veja o A.P.O.L.O. pensar.
"""

import asyncio
import logging
import os
import threading

from src.llm import KEEP_ALIVE_HEAVY, chat_resilient, stream_sync
from src.prompts import RESEARCH_PLAN_PROMPT, RESEARCH_SYNTHESIS_PROMPT, RESEARCH_REFINE_PROMPT
from src.rerank import rerank, tokenize
from src.web_search import web_research

logger = logging.getLogger(__name__)

MAX_SUBQUESTIONS = 3
MIN_SUBQUESTIONS = 2
MAX_SUBQUESTIONS_HARD = 5
RECALL_PER_SUBQ  = 2
WEB_PER_SUBQ     = 2
WEB_CTX_CHARS    = 700
SNIPPET_CHARS    = 380
MAX_DOSSIER_MEM  = 5   # teto de memórias únicas no dossiê (controla tamanho do prompt)
SAVE_MIN_ANSWER  = 400 # só persiste descobertas se a síntese for substancial
REFINE_ENABLED   = os.getenv("RESEARCH_REFINE", "1") not in ("0", "false", "False", "")
REFINE_MIN_ANSWER = 400 # só refina se a 1ª síntese já for substancial

_COMPLEX_CUES = (
    "compar", "trade-off", "tradeoff", "arquitetura", "architecture", "vs ", " versus ",
    "diferen", "melhor", "prós e contras", "pros e contras", "estratégia", "design",
    "como implementar", "passo a passo", "profund", "detalhad", "completo",
)


def _decide_n(question: str) -> int:
    """Nº de frentes adaptativo: perguntas complexas/longas merecem mais investigação."""
    q = (question or "").strip()
    ql = q.lower()
    n = MAX_SUBQUESTIONS
    if len(q) > 200 or sum(c in ql for c in _COMPLEX_CUES) >= 2:
        n = MAX_SUBQUESTIONS_HARD
    elif len(q) < 60 and not any(c in ql for c in _COMPLEX_CUES):
        n = MIN_SUBQUESTIONS
    return max(MIN_SUBQUESTIONS, min(MAX_SUBQUESTIONS_HARD, n))


def _worth_saving(answer: str, sources: list) -> bool:
    """Só guarda na memória descobertas substanciais e embasadas em fontes reais —
    evita persistir alucinação do modelo como se fosse conhecimento."""
    return bool(answer and len(answer.strip()) >= SAVE_MIN_ANSWER and sources)


class DeepResearchAgent:
    """Orquestra plano → pesquisa paralela → síntese fundamentada."""

    def __init__(self, model: str, rag=None, knowledge_db=None):
        self.model = model
        self.rag = rag
        self.knowledge_db = knowledge_db

    # ── Etapa 1: planejamento ─────────────────────────────────
    async def _plan(self, question: str, n: int = MAX_SUBQUESTIONS) -> list[str]:
        prompt = RESEARCH_PLAN_PROMPT.format(question=question, n=n)
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient, self.model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE_HEAVY,
                ),
                timeout=120.0,
            )
        except Exception as e:
            logger.warning(f"[research] planejamento falhou: {e}")
            return []
        return _parse_subquestions(text, n)

    # ── Etapa 2: pesquisa por frente ──────────────────────────
    async def _gather(self, subq: str) -> dict:
        memories: list[dict] = []
        if self.rag:
            try:
                memories = await asyncio.to_thread(self.rag.recall, subq, RECALL_PER_SUBQ)
            except Exception as e:
                logger.debug(f"[research] recall '{subq[:40]}': {e}")

        web_context, web_sources = await self._web(subq)

        # 2º round: se a frente veio totalmente vazia, tenta uma query simplificada
        # (núcleo de palavras-chave) — recupera de buscas malformuladas/ruidosas.
        if not memories and not web_sources:
            simpler = _simplify_query(subq)
            if simpler and simpler != subq.lower():
                logger.debug(f"[research] 2º round: '{subq[:40]}' → '{simpler}'")
                web_context, web_sources = await self._web(simpler)

        # Reranqueia as fontes web por relevância à sub-pergunta (lexical, pois o FTS/DDG
        # ordena mal) — a fonte mais on-topic aparece primeiro no dossiê.
        if len(web_sources) > 1:
            try:
                web_sources = rerank(subq, web_sources, len(web_sources))
            except Exception as e:
                logger.debug(f"[research] rerank web: {e}")

        return {"subq": subq, "memories": memories,
                "web_sources": web_sources, "web_context": web_context}

    async def _web(self, query: str) -> tuple[str, list[dict]]:
        try:
            return await asyncio.wait_for(
                web_research(query, max_results=WEB_PER_SUBQ), timeout=18.0
            )
        except Exception as e:
            logger.debug(f"[research] web '{query[:40]}': {e}")
            return "", []

    # ── Etapa 3: síntese em streaming (não bloqueia o event loop) ──
    async def _stream_synthesis(self, prompt: str):
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def worker():
            try:
                for piece in stream_sync(
                    self.model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE_HEAVY,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, ("token", piece))
            except Exception as e:
                loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
            finally:
                loop.call_soon_threadsafe(q.put_nowait, ("end", None))

        threading.Thread(target=worker, daemon=True).start()
        while True:
            kind, val = await q.get()
            if kind == "end":
                break
            yield kind, val

    # ── Persistência das descobertas (conhecimento que compõe) ──
    def _persist_findings(self, question: str, answer: str, sources: list) -> None:
        """Guarda a síntese da pesquisa na memória de longo prazo (Supabase + RAG),
        para que pesquisas futuras já partam do que o A.P.O.L.O. descobriu."""
        url = f"research://apolo/{abs(hash(question.strip().lower())) & 0xFFFFFFFF:08x}"
        try:
            from src.topics import classify_sector
            sector = classify_sector(question)
        except Exception:
            sector = "outros"
        if self.knowledge_db:
            try:
                self.knowledge_db.save(
                    f"Pesquisa: {question[:120]}", url, answer[:8000],
                    "deep_research", [sector],
                )
            except Exception as e:
                logger.debug(f"[research] persist knowledge: {e}")
        if self.rag:
            try:
                self.rag.add_example(
                    f"# {question[:120]}\nFonte: pesquisa profunda\n\n{answer[:2000]}",
                    f"research_{abs(hash(question.strip().lower())) & 0xFFFFFFFF:08x}",
                )
            except Exception as e:
                logger.debug(f"[research] persist rag: {e}")

    # ── 2º round: autocrítica que COMPLEMENTA (não reescreve) ──
    async def _refine(self, question: str, answer: str) -> str:
        """Critica a própria síntese; se faltar algo, retorna um '## Complemento'.
        Retorna string vazia se já estiver completa (verdict COMPLETO) ou em erro."""
        prompt = RESEARCH_REFINE_PROMPT.format(question=question, answer=answer[:4000])
        try:
            verdict = (await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient, self.model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE_HEAVY,
                ),
                timeout=120.0,
            ) or "").strip()
        except Exception as e:
            logger.debug(f"[research] refine: {e}")
            return ""
        return _parse_refinement(verdict)

    # ── Orquestração pública (async generator de eventos) ─────
    async def research(self, question: str):
        yield {"type": "step", "icon": "🧩", "message": "Decompondo a pergunta em frentes de investigação..."}

        subs = await self._plan(question, _decide_n(question))
        if not subs:
            subs = [question]  # fallback: pesquisa direta da pergunta
            yield {"type": "step", "icon": "🗺️", "message": "Investigando a pergunta diretamente"}
        else:
            yield {"type": "step", "icon": "🗺️", "message": f"{len(subs)} frentes de investigação definidas"}
            for i, s in enumerate(subs, 1):
                yield {"type": "step", "icon": "▸", "message": f"{i}. {s}"}

        yield {"type": "step", "icon": "🔎", "message": "Pesquisando memória + web em paralelo..."}
        results = await asyncio.gather(*[self._gather(s) for s in subs], return_exceptions=True)
        results = [r for r in results if isinstance(r, dict)]

        dossier, sources = _build_dossier(results)
        n_mem = sum(len(r["memories"]) for r in results)
        n_web = sum(len(r["web_sources"]) for r in results)
        yield {"type": "step", "icon": "📚",
               "message": f"{n_mem} memórias internas + {n_web} fontes web reunidas"}

        if not sources:
            yield {"type": "step", "icon": "🧠",
                   "message": "Sem evidências externas — respondendo com o conhecimento do modelo"}

        yield {"type": "status", "message": "Sintetizando resposta fundamentada..."}

        prompt = RESEARCH_SYNTHESIS_PROMPT.format(question=question, dossier=dossier or "(sem evidências reunidas)")
        answer = ""
        async for kind, val in self._stream_synthesis(prompt):
            if kind == "token":
                answer += val
                yield {"type": "token", "content": val}
            elif kind == "error":
                yield {"type": "error", "message": f"Falha na síntese: {val}"}
                return

        # ── 2º round: autocrítica → complementa o que ficou faltando (aditivo) ──
        if REFINE_ENABLED and len(answer.strip()) >= REFINE_MIN_ANSWER:
            yield {"type": "step", "icon": "🔎", "message": "Revisando a própria resposta e completando lacunas..."}
            complement = await self._refine(question, answer)
            if complement:
                yield {"type": "token", "content": "\n\n" + complement}
                answer += "\n\n" + complement
                yield {"type": "step", "icon": "✨", "message": "Resposta complementada após autocrítica"}

        # Compõe conhecimento: guarda a descoberta na memória (background, não atrasa o done).
        if _worth_saving(answer, sources):
            yield {"type": "step", "icon": "💾", "message": "Guardando a descoberta na memória de longo prazo"}
            asyncio.create_task(asyncio.to_thread(self._persist_findings, question, answer, sources))
            saved = True
        else:
            saved = False

        yield {"type": "done", "answer": answer, "sources": sources,
               "subquestions": subs, "n_memories": n_mem, "n_web": n_web, "saved": saved}


# ── Helpers ───────────────────────────────────────────────────

def _parse_refinement(verdict: str) -> str:
    """Interpreta a saída da autocrítica: 'COMPLETO' → '' (nada a acrescentar);
    senão devolve o complemento, garantindo o cabeçalho '## Complemento'.
    Modelos leves às vezes vazam ruído — só aceita complementos substanciais."""
    v = (verdict or "").strip()
    if not v or v.upper().startswith("COMPLETO"):
        return ""
    # Remove um eventual prefixo de scaffolding antes do cabeçalho.
    idx = v.find("## Complemento")
    if idx > 0:
        v = v[idx:]
    elif "## Complemento" not in v:
        # Sem cabeçalho explícito: aceita só se tiver conteúdo de verdade.
        if len(v) < 40:
            return ""
        v = "## Complemento\n" + v
    return v if len(v) >= 50 else ""


def _simplify_query(subq: str) -> str:
    """Reduz uma sub-pergunta ao núcleo de palavras-chave (até 6 termos significativos)
    para um 2º round de busca quando a 1ª tentativa não achou nada."""
    toks = [t for t in tokenize(subq)]  # sem stopwords, ≥3 chars
    # Preserva a ordem de aparição na pergunta original.
    seen, ordered = set(), []
    for w in re_findall_words(subq):
        wl = w.lower()
        if wl in toks and wl not in seen:
            seen.add(wl)
            ordered.append(wl)
    return " ".join(ordered[:6])


def re_findall_words(text: str) -> list[str]:
    import re
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+", text or "")


def _parse_subquestions(text: str, n: int) -> list[str]:
    """Extrai sub-perguntas — aceita '- ', '* ', '• ' e listas numeradas '1.' / '1)'."""
    import re
    subs: list[str] = []
    bullet = re.compile(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)(.*)$")
    for line in text.splitlines():
        m = bullet.match(line)
        if not m:
            continue
        q = m.group(1).strip(" *_`\"'").strip()
        if len(q) > 8 and q.lower() not in {s.lower() for s in subs}:
            subs.append(q)
    return subs[:n]


def _build_dossier(results: list[dict]) -> tuple[str, list[dict]]:
    """Monta o dossiê numerado e a lista de fontes (memória + web) para citação."""
    sources: list[dict] = []
    index: dict[str, int] = {}
    lines: list[str] = []

    def cite(stype: str, title: str, url: str) -> int:
        key = (url or title or "").lower().strip()
        if key and key in index:
            return index[key]
        n = len(sources) + 1
        if key:
            index[key] = n
        sources.append({"n": n, "type": stype,
                        "title": (title or url or "fonte")[:140], "url": url})
        return n

    seen_mem: set[str] = set()   # evita repetir o snippet da mesma memória entre frentes
    mem_count = 0
    for r in results:
        lines.append(f"\n### Frente investigada: {r['subq']}")
        for m in r.get("memories", []):
            key = (m.get("source") or m.get("title") or "").lower().strip()
            n = cite("knowledge", m.get("title") or "memória", m.get("source") or "")
            # Cita a fonte sempre, mas só inclui o corpo da memória uma vez
            if key in seen_mem or mem_count >= MAX_DOSSIER_MEM:
                lines.append(f"[{n}] 📚 MEMÓRIA — {m.get('title') or '—'} (ver acima)")
                continue
            seen_mem.add(key)
            mem_count += 1
            rel = m.get("relevance")
            rel_txt = f" (relevância {rel})" if isinstance(rel, (int, float)) else ""
            lines.append(f"[{n}] 📚 MEMÓRIA — {m.get('title') or '—'}{rel_txt}\n{m.get('snippet', '')[:SNIPPET_CHARS]}")
        for s in r.get("web_sources", []):
            n = cite("web", s.get("title", ""), s.get("url", ""))
            snip = (s.get("snippet") or "").strip()
            tail = f"\n{snip[:SNIPPET_CHARS]}" if snip else ""
            lines.append(f"[{n}] 🌐 WEB — {s.get('title') or s.get('url')}{tail}")
        if r.get("web_context"):
            lines.append(f"Trechos da web desta frente:\n{r['web_context'][:WEB_CTX_CHARS]}")

    return "\n".join(lines), sources
