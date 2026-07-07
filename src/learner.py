"""
A.P.O.L.O. Learner — Pipeline contínuo de aprendizado autônomo.

Arquitetura de pipeline (IO ≠ CPU sobrepostos):
  3 Fetchers  → correm em paralelo (IO-bound: HTTP + DuckDuckGo)
  1 Summarizer → único consumidor do Ollama (CPU-bound)
  1 Saver     → persiste e dispara síntese a cada N itens

Resultado: enquanto Ollama processa 1 tópico (~90s), os fetchers
já buscaram os próximos 3 — zero tempo ocioso.
"""

import asyncio
import logging
import os
import re
from datetime import datetime

from src.agents import (
    DocCrawlerAgent, WebSearchAgent, TrendAgent, SynthesisAgent, GitHubAgent,
    EncyclopediaAgent, BookAgent,
)
from src.llm import KEEP_ALIVE, chat_resilient
from src.topics import classify_sector
from src.web_search import web_research, fetch_page_text

logger = logging.getLogger(__name__)

from src.learner_types import (  # noqa: F401 (re-exporta p/ compat)
    FETCH_QUEUE_MAX, SYNTHESIS_EVERY, LLM_DOWN_BACKOFF, MAX_CONTENT_CHARS,
    PERSIST_TIMEOUT,
    FetchedItem, LearnedItem,
    SUMMARIZE_PROMPT, SUMMARIZE_PROMPT_GERAL, GENERAL_CATEGORIES,
)
from src.learner_synthesis import (  # noqa: F401 (re-exporta p/ compat)
    _extract_self_queries, _cluster_topics, _build_synthesis_prompt,
)


class LearningEngine:
    """Motor de aprendizado com pipeline IO/CPU sobrepostos."""

    def __init__(
        self,
        model: str = "qwen2.5-coder:14b",
        rag=None,
        knowledge_db=None,
        db=None,
        interval_seconds: int = 60,   # não usado no pipeline, mantido para compatibilidade
        summarize_model: str | None = None,
        gpu_gate=None,
    ):
        self.model = model
        # Cede a GPU às requisições do usuário (resposta interativa tem prioridade).
        self.gpu_gate = gpu_gate
        # Modelo dedicado à sumarização — pode ser menor/mais rápido (ex: codellama).
        # Definido via env SUMMARIZE_MODEL; cai para o modelo principal se ausente.
        self.summarize_model = summarize_model or os.getenv("SUMMARIZE_MODEL", "").strip() or model
        self.rag = rag
        self.knowledge_db = knowledge_db
        self.db = db
        self.running = False

        agent_kwargs = dict(model=model, rag=rag, knowledge_db=knowledge_db, db=db)
        self._doc_agent          = DocCrawlerAgent(**agent_kwargs)
        self._search_agent       = WebSearchAgent(**agent_kwargs)
        self._trend_agent        = TrendAgent(**agent_kwargs)
        self._github_agent       = GitHubAgent(**agent_kwargs)
        self._encyclopedia_agent = EncyclopediaAgent(**agent_kwargs)
        self._book_agent         = BookAgent(**agent_kwargs)
        self._synthesis_agent    = SynthesisAgent(**agent_kwargs)

        # Anti-repetição in-flight: tópicos atualmente na fila ou em sumarização.
        # Sem isto, um tópico "elegível" era re-enfileirado a cada ciclo do fetcher
        # até LOTAR a fila com cópias (bug real: 6× "Teoria da relatividade" — o
        # tópico só vira "estudado" DEPOIS do save, ~2 min depois do 1º fetch).
        self._inflight: set[str] = set()
        # Tópicos cuja sumarização falhou 2× — desistimos deles NESTA sessão
        # (nada de salvar conteúdo cru como "conhecimento", nem re-tentar em loop).
        self._skip_session: set[str] = set()
        # Falha de INFRAESTRUTURA (Ollama inacessível/circuito aberto) — não é
        # culpa do tópico: o summarizer pausa em vez de descartar o currículo.
        self._llm_down = False
        self._llm_down_notified = False

        # Filas do pipeline
        self._fetch_queue: asyncio.Queue[FetchedItem] = asyncio.Queue(maxsize=FETCH_QUEUE_MAX)
        self._user_queue:  asyncio.Queue[str]         = asyncio.Queue()
        # Fila auto-dirigida: tópicos que o próprio A.P.O.L.O. decidiu estudar
        self._self_queue:  asyncio.Queue[str]         = asyncio.Queue(maxsize=24)

        # Tasks do pipeline
        self._tasks: list[asyncio.Task] = []

        # Contadores e estado
        self._saved_count        = 0
        self._fetched_count      = 0
        self._self_directed_count = 0
        self._next_studies: list[str] = []   # currículo auto-gerado mais recente
        self._gap_count = 0                   # perguntas sem memória → estudadas
        self._recent_gaps: list[str] = []     # lacunas recentes detectadas no chat
        self._start_time: datetime | None = None
        self._active_summarizing = ""

        self.stats: dict = {
            "running": False,
            "learned_today": 0,
            "total_learned": 0,
            "current_topic": "",
            "current_source": "",
            "last_topic": "",
            "last_learned_at": "",
            "activity": [],
            "agents": [],
            "queue_depth": 0,
            "throughput_hour": 0,
            "total_session": 0,
        }

    # ── Anti-repetição ────────────────────────────────────────

    @staticmethod
    def _norm(topic: str) -> str:
        return re.sub(r"\s+", " ", (topic or "").strip().lower())

    def _reserve(self, topic: str) -> bool:
        """Reserva um tópico para estudo. False = já está na fila/em sumarização."""
        key = self._norm(topic)
        if not key or key in self._inflight:
            return False
        self._inflight.add(key)
        return True

    def _release(self, topic: str) -> None:
        self._inflight.discard(self._norm(topic))

    def _already_known(self, topic: str, url: str = "") -> bool:
        """Já estudado (por tópico OU por URL) ou desistido nesta sessão? Vale
        para TODOS os agentes — antes só o doc_agent checava URL."""
        if self._norm(topic) in self._skip_session:
            return True
        if not self.db:
            return False
        if url and self.db.is_url_studied(url):
            return True
        return self.db.is_topic_studied(topic)

    # ── API pública ───────────────────────────────────────────

    def add_user_topic(self, question: str) -> None:
        if len(question) > 10:
            self._user_queue.put_nowait(question[:200])

    def note_gap(self, topic: str) -> None:
        """O chat não tinha memória sobre isto → registra a lacuna como prioridade.
        A pergunta já entrou na user_queue (prioridade máxima); aqui só rastreamos
        para tornar a autonomia visível no painel Mente."""
        topic = (topic or "").strip()
        if len(topic) <= 10:
            return
        self._gap_count += 1
        short = topic[:120]
        if short in self._recent_gaps:
            self._recent_gaps.remove(short)
        self._recent_gaps.insert(0, short)
        self._recent_gaps = self._recent_gaps[:10]

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.stats["running"] = True
        self._start_time = datetime.now()
        self._saved_count = 0
        self._inflight.clear()
        self._skip_session.clear()
        self._llm_down = False
        self._llm_down_notified = False

        # Lança workers do pipeline
        self._tasks = [
            asyncio.create_task(self._fetcher(self._doc_agent,          delay=0),  name="fetcher-doc"),
            asyncio.create_task(self._fetcher(self._search_agent,       delay=2),  name="fetcher-web"),
            asyncio.create_task(self._fetcher(self._trend_agent,        delay=4),  name="fetcher-trend"),
            asyncio.create_task(self._fetcher(self._github_agent,       delay=6),  name="fetcher-github"),
            asyncio.create_task(self._fetcher(self._encyclopedia_agent, delay=8),  name="fetcher-enciclopedia"),
            asyncio.create_task(self._fetcher(self._book_agent,         delay=10), name="fetcher-livros"),
            asyncio.create_task(self._summarize_worker(),                          name="summarizer"),
            asyncio.create_task(self._save_worker(),                               name="saver"),
        ]
        logger.info("A.P.O.L.O. Learner INICIADO — pipeline contínuo — 6 fetchers + 1 summarizer")

    async def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self.stats["running"] = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self.stats.update({"current_topic": "", "current_source": "", "agents": []})
        logger.info("A.P.O.L.O. Learner PARADO")

    async def study_now(self, topic: str) -> dict:
        """Estuda tópico imediatamente — injeta na fila de usuário com prioridade."""
        logger.info(f"[study_now] {topic}")
        self.stats["current_topic"] = topic
        try:
            web_context, sources = await asyncio.wait_for(
                web_research(topic, max_results=2), timeout=20.0
            )
        except asyncio.TimeoutError:
            return {"ok": False, "topic": topic, "error": "timeout"}

        if not web_context or not sources:
            return {"ok": False, "topic": topic, "error": "sem resultados"}

        url = sources[0]["url"]
        summary = await self._summarize(topic, web_context, "user_question")
        if summary is None:
            return {"ok": False, "topic": topic, "error": "síntese falhou — tente de novo"}
        item = LearnedItem(topic=topic, url=url, summary=summary,
                           category="user_question", agent_name="study_now")
        await self._persist(item)
        self._record_activity(item)
        self.stats["current_topic"] = ""
        return {"ok": True, "topic": topic, "url": url, "summary": summary,
                "agent": "study_now", "time": item.timestamp}

    @staticmethod
    def _looks_raw(summary: str) -> bool:
        """Heurística: síntese de verdade tem estrutura markdown (seções '##');
        conteúdo cru salvo pelos timeouts antigos não tem — é texto corrido."""
        s = (summary or "").strip()
        return len(s) >= 300 and "##" not in s

    async def repair_raw_summaries(self, limit: int = 8) -> dict:
        """Repara conhecimentos salvos CRUS (timeouts antigos que gravaram o
        texto truncado como 'síntese'): re-sintetiza a partir do próprio texto
        salvo, com o template certo da categoria, e atualiza in-place (log
        SQLite + índice RAG). Roda em background — 1 chamada de LLM por item."""
        if not self.db:
            return {"ok": False, "error": "sem banco"}
        rows = await asyncio.to_thread(self.db.get_learning_history, 300)
        raw_rows = [r for r in rows if self._looks_raw(r.get("summary", ""))][:limit]
        repaired, failed = 0, 0
        for r in raw_rows:
            summary = await self._summarize(
                r["topic"], r["summary"], r.get("category") or "web_search")
            if not summary or self._looks_raw(summary):
                failed += 1
                continue
            await asyncio.to_thread(self.db.update_topic_summary, r["id"], summary)
            # Reindexa o recall com a síntese boa (doc_id por tópico → upsert).
            if self.rag:
                try:
                    key = r["topic"].strip().lower()
                    doc_id = f"repair_{hash(key) & 0xFFFFFFFF:08x}"
                    await asyncio.to_thread(
                        self.rag.add_example,
                        f"# {r['topic']}\nFonte: {r.get('url', '')}\n\n{summary}", doc_id)
                except Exception as e:
                    logger.debug(f"[repair] rag: {e}")
            repaired += 1
            logger.info(f"[repair] 🩹 re-sintetizado: {r['topic'][:60]}")
        if self.db and (repaired or raw_rows):
            try:
                self.db.add_notification(
                    f"🩹 Reparo de sínteses: {repaired} re-sintetizada(s), "
                    f"{failed} falharam, {len(raw_rows)} encontradas", kind="info")
            except Exception:
                pass
        return {"ok": True, "found": len(raw_rows), "repaired": repaired, "failed": failed}

    def get_status(self) -> dict:
        if self.db:
            db_stats = self.db.get_learning_stats()
            self.stats["learned_today"]  = db_stats["today"]
            self.stats["total_learned"]  = db_stats["total"]

        self.stats["queue_depth"]         = self._fetch_queue.qsize()
        self.stats["total_session"]       = self._saved_count
        self.stats["summarize_model"]     = self.summarize_model
        self.stats["llm_down"]            = self._llm_down
        self.stats["current_topic"]       = self._active_summarizing
        self.stats["self_directed_count"] = self._self_directed_count
        self.stats["self_queue_depth"]    = self._self_queue.qsize()
        self.stats["next_studies"]        = self._next_studies
        self.stats["gap_count"]           = self._gap_count
        self.stats["recent_gaps"]         = self._recent_gaps

        # Calcula throughput (itens/hora)
        if self._start_time and self._saved_count > 0:
            elapsed = (datetime.now() - self._start_time).total_seconds() / 3600
            self.stats["throughput_hour"] = round(self._saved_count / elapsed) if elapsed > 0 else 0

        self.stats["agents"] = [
            self._doc_agent.get_status(),
            self._search_agent.get_status(),
            self._trend_agent.get_status(),
            self._github_agent.get_status(),
            self._encyclopedia_agent.get_status(),
            self._book_agent.get_status(),
            {"name": "synthesizer", "active": self._synthesis_agent.active,
             "current_topic": self._synthesis_agent.current_topic},
            {"name": "auto_curriculum",
             "active": self._self_queue.qsize() > 0,
             "current_topic": (self._next_studies[0] if self._next_studies else "")},
        ]
        return {**self.stats}

    # ── Workers do pipeline ───────────────────────────────────

    async def _fetcher(self, agent, delay: float = 0) -> None:
        """Worker de fetch — corre continuamente, alimenta fetch_queue."""
        await asyncio.sleep(delay)  # escalonamento de início
        while self.running:
            # Prioridades (apenas no fetcher-web):
            #   1º tópico do usuário  2º currículo auto-dirigido do A.P.O.L.O.
            # Blindado: erro aqui não pode matar o fetcher (senão essa fonte de
            # tópicos morre em silêncio e o aprendizado míngua).
            if agent is self._search_agent:
                try:
                    if not self._user_queue.empty():
                        topic = self._user_queue.get_nowait()
                        await self._fetch_and_enqueue_search(topic, "user_question", agent.name)
                        continue
                    if not self._self_queue.empty():
                        topic = self._self_queue.get_nowait()
                        self._self_directed_count += 1
                        await self._fetch_and_enqueue_search(topic, "self_directed", "auto_curriculum")
                        continue
                except Exception as e:
                    logger.debug(f"[{agent.name}] priority fetch error: {e}")
                    await asyncio.sleep(1)

            # Fetch normal do agente
            try:
                agent.active = True
                topic, url_hint = await agent.next_topic()
                agent.current_topic = topic

                if url_hint:
                    # Doc / GitHub / Enciclopédia / Livros — fetch direto da URL.
                    # Anti-repetição em DUAS camadas: já estudado (tópico OU URL,
                    # p/ todos os agentes) e in-flight (já está na fila esperando
                    # sumarização — a janela em que o bug das cópias acontecia).
                    if self._already_known(topic, url_hint) or not self._reserve(topic):
                        agent.active = False
                        agent.current_topic = ""
                        await asyncio.sleep(1)
                        continue
                    enqueued = False
                    try:
                        content = await asyncio.wait_for(fetch_page_text(url_hint), timeout=15.0)
                        if content and len(content) > 100:
                            item = FetchedItem(topic=topic, url=url_hint,
                                               content=content[:MAX_CONTENT_CHARS],
                                               category=agent.category, agent_name=agent.name)
                            await self._fetch_queue.put(item)
                            self._fetched_count += 1
                            enqueued = True
                    finally:
                        if not enqueued:
                            self._release(topic)
                else:
                    # Search — DuckDuckGo
                    await self._fetch_and_enqueue_search(topic, agent.category, agent.name)

            except asyncio.TimeoutError:
                logger.debug(f"[{agent.name}] fetch timeout")
            except Exception as e:
                logger.debug(f"[{agent.name}] fetch error: {e}")
            finally:
                agent.active = False
                agent.current_topic = ""

            # Pequena pausa entre fetches do mesmo agente
            await asyncio.sleep(3)

    async def _fetch_and_enqueue_search(self, topic: str, category: str, agent_name: str) -> None:
        # Anti-duplicação: não re-estuda tópicos de rotação já aprendidos. Perguntas do
        # usuário e o currículo auto-dirigido podem repetir de propósito, então passam.
        if category not in ("user_question", "self_directed") and self._already_known(topic):
            return
        # In-flight: nunca duas cópias do mesmo tópico na fila ao mesmo tempo
        # (vale para todas as categorias — repetir DEPOIS de salvo é permitido).
        if not self._reserve(topic):
            return
        enqueued = False
        try:
            web_context, sources = await asyncio.wait_for(
                web_research(topic, max_results=2), timeout=18.0
            )
            if web_context and sources:
                item = FetchedItem(topic=topic, url=sources[0]["url"],
                                   content=web_context[:MAX_CONTENT_CHARS],
                                   category=category, agent_name=agent_name)
                await self._fetch_queue.put(item)
                self._fetched_count += 1
                enqueued = True
        except Exception as e:
            logger.debug(f"[search] {topic[:40]}: {e}")
        finally:
            if not enqueued:
                self._release(topic)

    async def _summarize_worker(self) -> None:
        """Único consumidor do Ollama — serializa LLM para evitar contenção.
        Blindado: uma exceção em _process_item NÃO pode matar o worker (se morresse,
        ninguém drena a fila → fetchers bloqueiam no put → CONGELAMENTO permanente,
        exatamente o 'travou e não conseguiu mais')."""
        while self.running:
            try:
                item = await asyncio.wait_for(self._fetch_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"[summarizer] erro ao pegar item: {e}")
                await asyncio.sleep(1)
                continue
            try:
                await self._process_item(item)
            except Exception as e:
                # Não deixa o item preso in-flight e segue vivo.
                logger.warning(f"[summarizer] _process_item falhou ({item.topic[:40]}): {e}")
                self._release(item.topic)
                await asyncio.sleep(1)

    async def _process_item(self, item: FetchedItem) -> None:
        """Sumariza um item. Falhou? NÃO salva conteúdo cru como 'conhecimento':
        re-enfileira UMA vez (o fetch já foi pago); na 2ª falha desiste do tópico
        nesta sessão. Antes, todo timeout salvava lixo truncado na base."""
        self._active_summarizing = item.topic
        logger.info(f"[summarizer] {item.agent_name} → {item.topic[:60]}")
        try:
            summary = await self._summarize(item.topic, item.content, item.category)
            if summary is None:
                if self._llm_down:
                    # Ollama fora do ar — NÃO é culpa do tópico: devolve à fila
                    # sem contar tentativa e PAUSA até o motor voltar (bug real:
                    # com o Ollama desligado, 48 tópicos foram buscados na web e
                    # descartados um a um em minutos).
                    if not self._llm_down_notified:
                        self._llm_down_notified = True
                        logger.warning("[summarizer] ⏸️ Ollama fora do ar — estudo "
                                       f"PAUSADO (re-checa a cada {LLM_DOWN_BACKOFF:.0f}s; "
                                       "nada será descartado)")
                        if self.db:
                            try:
                                self.db.add_notification(
                                    "⏸️ Ollama fora do ar — o estudo está pausado até ele "
                                    "voltar (nenhum tópico foi descartado)", kind="info")
                            except Exception:
                                pass
                    try:
                        self._fetch_queue.put_nowait(item)
                    except asyncio.QueueFull:
                        self._release(item.topic)   # re-buscado numa rodada futura
                    await asyncio.sleep(LLM_DOWN_BACKOFF)
                    return
                if item.retries < 1:
                    item.retries += 1
                    try:
                        self._fetch_queue.put_nowait(item)   # 2ª chance, sem re-fetch
                        logger.info(f"[summarizer] re-tentará '{item.topic[:50]}'")
                        return
                    except asyncio.QueueFull:
                        pass  # fila cheia → desiste direto
                self._skip_session.add(self._norm(item.topic))
                self._release(item.topic)
                logger.warning(f"[summarizer] desistiu de '{item.topic[:50]}' nesta sessão "
                               f"(síntese falhou {item.retries + 1}×; nada foi salvo)")
                return
            learned = LearnedItem(
                topic=item.topic, url=item.url, summary=summary,
                category=item.category, agent_name=item.agent_name,
            )
            # Passa para o saver via atributo (evita mais uma fila)
            asyncio.create_task(self._save_and_record(learned))
        finally:
            self._active_summarizing = ""

    async def _save_worker(self) -> None:
        """Worker de controle — mantém o loop vivo, emite status e DETECTA STALL.
        Um pipeline que para de progredir em silêncio foi exatamente o bug 'estudou
        45 e travou'; aqui ele grita (WARNING + 1 notificação) com o diagnóstico."""
        prev_saved = prev_fetched = -1
        stalled_cycles = 0
        stall_notified = False
        while self.running:
            await asyncio.sleep(30)
            if not self.running:
                break
            q = self._fetch_queue.qsize()
            logger.info(
                f"A.P.O.L.O. pipeline — fila:{q} | salvos:{self._saved_count} | "
                f"buscados:{self._fetched_count}"
            )
            # Sem progresso (nem salvou, nem buscou) desde o último ciclo?
            no_progress = (self._saved_count == prev_saved and
                           self._fetched_count == prev_fetched)
            prev_saved, prev_fetched = self._saved_count, self._fetched_count
            if no_progress:
                stalled_cycles += 1
            else:
                stalled_cycles = 0
                stall_notified = False
            # ~2 min parado com o motor ligado → algo travou; exponha a causa provável.
            if stalled_cycles >= 4:
                causa = ("Ollama fora do ar" if self._llm_down else
                         "fila cheia (summarizer preso)" if q >= FETCH_QUEUE_MAX else
                         "sem tópicos novos (agentes esgotados / rede)")
                logger.warning(
                    f"[pipeline] ⚠️ SEM PROGRESSO há ~{stalled_cycles * 30}s — "
                    f"provável: {causa} | fila:{q} in-flight:{len(self._inflight)} "
                    f"llm_down:{self._llm_down} self_q:{self._self_queue.qsize()}"
                )
                if self.db and not stall_notified:
                    stall_notified = True
                    try:
                        self.db.add_notification(
                            f"⚠️ Aprendizado sem progresso — {causa}. Verifique.",
                            kind="info")
                    except Exception:
                        pass

    async def _save_and_record(self, item: LearnedItem) -> None:
        try:
            await self._persist(item)
            self._record_activity(item)
            self._saved_count += 1
        finally:
            # Só aqui o tópico sai do in-flight: a partir de agora ele consta como
            # "estudado" no banco, então os fetchers não o pegam de novo.
            self._release(item.topic)

        # Dispara síntese cross-domain a cada N itens
        if self._saved_count % SYNTHESIS_EVERY == 0:
            asyncio.create_task(self._run_deep_synthesis())

    # ── Aprendizado sob demanda (Coder → base) ────────────────

    async def learn_from_web(self, topic: str, content: str, url: str = "",
                             category: str = "web_search") -> bool:
        """Salva na base PERMANENTE um conhecimento que o Coder encontrou na web.
        Sintetiza primeiro (nunca grava conteúdo cru) e faz dedup por tópico já
        estudado — assim a próxima CONSULTAR do Coder já acha, sem re-pesquisar.
        Retorna True se salvou. Chamada em background pelo loop do Coder."""
        topic = (topic or "").strip()
        if not topic or len((content or "").strip()) < 120:
            return False
        # Já está na base? Não re-sintetiza (economiza uma chamada de LLM).
        try:
            if self.db and self.db.is_topic_studied(topic):
                return False
        except Exception:
            pass
        summary = await self._summarize(topic, content, category)
        if not summary:  # Ollama fora / timeout → não grava lixo cru
            return False
        item = LearnedItem(
            topic=topic[:200], url=url or f"web://coder/{topic[:80]}",
            summary=summary, category=category, agent_name="coder_web",
        )
        await self._persist(item)
        self._record_activity(item)
        self._saved_count += 1
        if self.db:
            try:
                self.db.add_notification(
                    f"📥 Coder aprendeu da web: {topic[:60]}", kind="learning")
            except Exception:
                pass
        return True

    # ── Síntese cross-domain ──────────────────────────────────

    async def _run_deep_synthesis(self) -> None:
        """Síntese profunda — cruza domínios e gera mapa de conhecimento."""
        if not self.db:
            return
        self._synthesis_agent.active = True

        history = self.db.get_learning_history(limit=30)
        if len(history) < 4:
            self._synthesis_agent.active = False
            return

        # Agrupa por domínio
        clusters = _cluster_topics(history)
        topic_label = f"Síntese #{self._saved_count // SYNTHESIS_EVERY}"
        self._synthesis_agent.current_topic = topic_label

        prompt = _build_synthesis_prompt(clusters)
        logger.info(f"[synthesizer] Síntese profunda — {len(history)} tópicos, {len(clusters)} clusters")

        try:
            if self.gpu_gate:
                await self.gpu_gate.wait_for_idle()
            synthesis = await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient, self.model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE,
                ),
                timeout=180.0,
            )
            url = f"synthesis://apolo/{self._saved_count:04d}"
            item = LearnedItem(
                topic=topic_label, url=url, summary=synthesis,
                category="synthesis", agent_name="synthesizer",
            )
            await self._persist(item)
            self._record_activity(item)
            logger.info(f"[synthesizer] ✓ Síntese salva — {len(synthesis)} chars")
            # Autonomia visível: avisa o usuário que cruzou domínios sozinho.
            if self.db:
                try:
                    self.db.add_notification(
                        f"🧠 Nova síntese cross-domain: {topic_label}", kind="synthesis")
                except Exception:
                    pass

            # ── AUTO-CURRÍCULO: A.P.O.L.O. decide o que estudar a seguir ──
            # Extrai as queries que ele mesmo gerou e as injeta na fila — zero
            # custo extra de LLM, fechando o loop de autonomia/automelhoria.
            self._enqueue_self_studies(_extract_self_queries(synthesis))
        except Exception as e:
            logger.warning(f"[synthesizer] Erro: {e}")
        finally:
            self._synthesis_agent.active = False
            self._synthesis_agent.current_topic = ""

    def _enqueue_self_studies(self, queries: list[str]) -> None:
        """Injeta na fila auto-dirigida os tópicos que o A.P.O.L.O. decidiu estudar."""
        if not queries:
            return
        added = []
        for q in queries:
            if self._self_queue.full():
                break
            # Evita re-estudar o que já sabe. As queries são TÓPICOS (não URLs), então
            # a checagem correta é is_topic_studied — antes usava is_url_studied, que
            # nunca casava e fazia o A.P.O.L.O. re-estudar tópicos conhecidos.
            if self.db and self.db.is_topic_studied(q):
                continue
            try:
                self._self_queue.put_nowait(q)
                added.append(q)
            except asyncio.QueueFull:
                break
        if added:
            self._next_studies = added
            logger.info(f"[auto-curriculum] 🎯 A.P.O.L.O. decidiu estudar: {added}")

    # ── Sumarização ───────────────────────────────────────────

    async def _summarize(self, topic: str, content: str,
                         category: str = "web_search") -> str | None:
        """Sintetiza o conteúdo com o template da categoria (tech vs geral).
        Retorna None quando falha — o chamador decide re-tentar/desistir;
        NUNCA devolve conteúdo cru fingindo ser síntese."""
        template = (SUMMARIZE_PROMPT_GERAL if category in GENERAL_CATEGORIES
                    else SUMMARIZE_PROMPT)
        prompt = template.format(topic=topic, content=content[:MAX_CONTENT_CHARS])
        try:
            if self.gpu_gate:
                await self.gpu_gate.wait_for_idle()
            out = await asyncio.wait_for(
                asyncio.to_thread(
                    chat_resilient, self.summarize_model,
                    [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE,
                ),
                timeout=120.0,
            )
            self._llm_down = False
            self._llm_down_notified = False
            return out if out and len(out.strip()) >= 80 else None
        except asyncio.TimeoutError:
            # Timeout = o motor está VIVO, só lento → falha de conteúdo.
            self._llm_down = False
            logger.warning(f"[summarizer] timeout — {topic[:50]}")
            return None
        except Exception as e:
            # Conexão recusada / circuito aberto = INFRAESTRUTURA fora.
            msg = str(e).lower()
            self._llm_down = any(k in msg for k in (
                "connect", "connection", "circuito", "indisponível",
                "unavailable", "refused"))
            logger.warning(f"[summarizer] erro — {e}")
            return None

    # ── Persistência ──────────────────────────────────────────

    async def _persist(self, item: LearnedItem) -> None:
        tasks = []
        if self.db:
            tasks.append(asyncio.to_thread(
                self.db.save_learned_topic,
                item.topic, item.url, item.summary[:2000], item.category,
            ))
        if self.knowledge_db:
            sector = classify_sector(item.topic)
            tasks.append(asyncio.to_thread(
                self.knowledge_db.save,
                f"[A.P.O.L.O.] {item.topic}", item.url, item.summary, item.category,
                [sector],  # tag de setor → alimenta o breakdown da Mente
            ))
        if tasks:
            # Teto de tempo: uma escrita lenta (ex.: Supabase em rede ruim) NUNCA pode
            # segurar o pipeline. Os clientes já têm timeout próprio (SUPABASE_TIMEOUT);
            # este wait_for é a 2ª linha de defesa contra pendurar o pipeline.
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True), timeout=PERSIST_TIMEOUT)
                for r in results:
                    if isinstance(r, Exception):
                        logger.debug(f"persist error: {r}")
            except asyncio.TimeoutError:
                logger.warning(f"[persist] escrita excedeu {PERSIST_TIMEOUT:.0f}s — "
                               f"segue sem travar ({item.topic[:50]})")
        if self.rag and item.summary:
            try:
                # doc_id estável por tópico (não pela URL): re-estudar faz UPSERT,
                # então o índice de recall não acumula duplicatas do mesmo assunto.
                key = item.topic.strip().lower()
                doc_id = f"{item.agent_name}_{hash(key) & 0xFFFFFFFF:08x}"
                await asyncio.wait_for(asyncio.to_thread(
                    self.rag.add_example,
                    f"# {item.topic}\nFonte: {item.url}\n\n{item.summary}", doc_id,
                ), timeout=PERSIST_TIMEOUT)
            except Exception as e:
                logger.debug(f"rag error: {e}")

    def _record_activity(self, item: LearnedItem) -> None:
        now = item.timestamp
        self.stats["last_topic"] = item.topic
        self.stats["last_learned_at"] = now
        entry = {"time": now, "topic": item.topic, "url": item.url,
                 "category": item.category, "agent": item.agent_name}
        self.stats["activity"] = [entry] + self.stats["activity"][:19]
        logger.info(f"✓ [{item.agent_name}] '{item.topic[:55]}'")


