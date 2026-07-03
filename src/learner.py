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
from dataclasses import dataclass, field

from src.agents import (
    DocCrawlerAgent, WebSearchAgent, TrendAgent, SynthesisAgent, GitHubAgent,
    EncyclopediaAgent, BookAgent,
)
from src.llm import KEEP_ALIVE, chat_resilient
from src.topics import classify_sector
from src.web_search import web_research, fetch_page_text

logger = logging.getLogger(__name__)

# ── Configuração do pipeline ──────────────────────────────────
FETCH_QUEUE_MAX   = 12   # buffer máximo de itens prontos para sumarizar
SYNTHESIS_EVERY   = 6    # dispara síntese a cada N itens salvos
MAX_CONTENT_CHARS = 3500 # limita conteúdo enviado ao LLM (mais rápido)


@dataclass
class FetchedItem:
    topic: str
    url: str
    content: str
    category: str
    agent_name: str
    retries: int = 0   # tentativas de sumarização já feitas


@dataclass
class LearnedItem:
    topic: str
    url: str
    summary: str
    category: str
    agent_name: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))


SUMMARIZE_PROMPT = """Você é A.P.O.L.O., agente de IA de elite em engenharia de software.

Sintetize "{topic}" em português brasileiro:

## Conceitos-chave
[3-4 pontos fundamentais — direto ao ponto]

## Como usar
[Código real ou passos concretos de produção]

## Integração
[Como se conecta com outras tecnologias do ecossistema]

## Insight A.P.O.L.O.
[O ponto mais importante para um engenheiro sênior lembrar]

CONTEÚDO:
{content}

Síntese (técnica, densa, sem enrolação):"""

# Conhecimento GERAL (enciclopédia, livros) não é código: sintetizar "Teoria da
# relatividade" com template de engenharia ("Como usar — código real") produzia
# lixo. Cada categoria usa o template certo.
SUMMARIZE_PROMPT_GERAL = """Você é A.P.O.L.O., mente enciclopédica de elite.

Sintetize "{topic}" em português brasileiro:

## Essência
[O conceito explicado em 2-3 frases claras]

## Pontos-chave
[4-6 fatos ou ideias centrais — os que realmente importam]

## Conexões
[Como este tema se liga a outras áreas do conhecimento]

## Insight A.P.O.L.O.
[A compreensão mais valiosa para reter deste tema]

CONTEÚDO:
{content}

Síntese (clara, densa, fiel ao conteúdo — não invente fatos):"""

# Categorias de conhecimento geral → usam o template enciclopédico.
GENERAL_CATEGORIES = {"encyclopedia", "book"}


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

    def get_status(self) -> dict:
        if self.db:
            db_stats = self.db.get_learning_stats()
            self.stats["learned_today"]  = db_stats["today"]
            self.stats["total_learned"]  = db_stats["total"]

        self.stats["queue_depth"]         = self._fetch_queue.qsize()
        self.stats["total_session"]       = self._saved_count
        self.stats["summarize_model"]     = self.summarize_model
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
            if agent is self._search_agent:
                if not self._user_queue.empty():
                    topic = self._user_queue.get_nowait()
                    await self._fetch_and_enqueue_search(topic, "user_question", agent.name)
                    continue
                if not self._self_queue.empty():
                    topic = self._self_queue.get_nowait()
                    self._self_directed_count += 1
                    await self._fetch_and_enqueue_search(topic, "self_directed", "auto_curriculum")
                    continue

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
        """Único consumidor do Ollama — serializa LLM para evitar contenção."""
        while self.running:
            try:
                item = await asyncio.wait_for(self._fetch_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            await self._process_item(item)

    async def _process_item(self, item: FetchedItem) -> None:
        """Sumariza um item. Falhou? NÃO salva conteúdo cru como 'conhecimento':
        re-enfileira UMA vez (o fetch já foi pago); na 2ª falha desiste do tópico
        nesta sessão. Antes, todo timeout salvava lixo truncado na base."""
        self._active_summarizing = item.topic
        logger.info(f"[summarizer] {item.agent_name} → {item.topic[:60]}")
        try:
            summary = await self._summarize(item.topic, item.content, item.category)
            if summary is None:
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
        """Worker de controle — só mantém o loop vivo e emite logs de status."""
        while self.running:
            await asyncio.sleep(30)
            if self.running:
                q = self._fetch_queue.qsize()
                logger.info(
                    f"A.P.O.L.O. pipeline — fila:{q} | salvos:{self._saved_count} | "
                    f"buscados:{self._fetched_count}"
                )

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
            return out if out and len(out.strip()) >= 80 else None
        except asyncio.TimeoutError:
            logger.warning(f"[summarizer] timeout — {topic[:50]}")
            return None
        except Exception as e:
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
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.debug(f"persist error: {r}")
        if self.rag and item.summary:
            try:
                # doc_id estável por tópico (não pela URL): re-estudar faz UPSERT,
                # então o índice de recall não acumula duplicatas do mesmo assunto.
                key = item.topic.strip().lower()
                doc_id = f"{item.agent_name}_{hash(key) & 0xFFFFFFFF:08x}"
                await asyncio.to_thread(
                    self.rag.add_example,
                    f"# {item.topic}\nFonte: {item.url}\n\n{item.summary}", doc_id,
                )
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


# ── Helpers de síntese cross-domain ──────────────────────────

DOMAIN_KEYWORDS = {
    "Python Core":      ["asyncio","typing","python","decorator","generator","dataclass","pep","gil"],
    "Web / API":        ["fastapi","django","rest","http","websocket","graphql","grpc","starlette","api"],
    "Banco de Dados":   ["postgresql","sql","sqlite","redis","mongodb","elasticsearch","query","orm","migration"],
    "Cloud / Infra":    ["aws","gcp","azure","lambda","s3","ecs","kubernetes","docker","terraform","helm"],
    "Data Engineering": ["kafka","airflow","spark","dbt","bigquery","pipeline","etl","streaming","duckdb"],
    "Arquitetura":      ["clean","ddd","cqrs","microservice","hexagonal","saga","event","pattern","solid"],
    "DevOps / CI/CD":   ["github actions","ci","cd","docker","deploy","pipeline","monitoring","observability"],
    "IA / ML":          ["llm","ai","ml","embedding","rag","langchain","ollama","model","vector","agent"],
    "Segurança":        ["auth","jwt","oauth","owasp","secret","security","ssl","zero trust"],
    "GitHub / OSS":     ["trending","github","readme","repository","open source"],
}


def _extract_self_queries(synthesis: str) -> list[str]:
    """Extrai as queries auto-geradas (linhas '🎯 QUERY: ...') da síntese."""
    import re
    queries: list[str] = []
    for line in synthesis.splitlines():
        if "QUERY:" not in line:
            continue
        q = line.split("QUERY:", 1)[1].strip(" *_`\"'-").strip()
        q = re.sub(r"\s+", " ", q)  # normaliza espaços internos
        # Sanidade: precisa parecer uma query buscável de verdade
        if 12 <= len(q) <= 140 and " " in q:
            queries.append(q)
    # Dedup por forma NORMALIZADA (ignora pontuação/maiúsculas) — assim
    # "Redis pub/sub" e "redis pub sub?" não viram dois estudos do mesmo tema.
    seen, unique = set(), []
    for q in queries:
        # Pontuação vira espaço (pub/sub == pub sub) e espaços são colapsados.
        key = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", q.lower())).strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:6]


def _cluster_topics(history: list[dict]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = {d: [] for d in DOMAIN_KEYWORDS}
    clusters["Outros"] = []
    for item in history:
        text = (item["topic"] + " " + (item["summary"] or "")[:200]).lower()
        placed = False
        for domain, keywords in DOMAIN_KEYWORDS.items():
            if any(k in text for k in keywords):
                clusters[domain].append(item["topic"][:80])
                placed = True
                break
        if not placed:
            clusters["Outros"].append(item["topic"][:80])
    return {k: v for k, v in clusters.items() if v}


SYNTHESIS_CROSS_PROMPT = """Você é A.P.O.L.O., arquiteto de sistemas de elite.

Você aprendeu os seguintes tópicos, agrupados por domínio:

{clusters_text}

Crie uma SÍNTESE ESTRATÉGICA DE CRUZAMENTO DE CONHECIMENTO:

## Mapa de Integração
[Como esses domínios se conectam numa stack real — desenhe o fluxo completo de uma aplicação moderna usando os componentes acima]

## Padrões Cross-Domain Identificados
[3-4 padrões que aparecem em múltiplos domínios — ex: "async aparece em Python, FastAPI, banco de dados e Kafka"]

## Stack de Referência A.P.O.L.O.
[Baseado no que foi estudado, qual seria a stack ideal para uma aplicação de produção? Por quê cada escolha?]

## Gaps de Conhecimento
[Que áreas importantes ainda não foram estudadas? Quais conexões estão faltando?]

## Próximos Estudos Estratégicos
Você é uma IA AUTÔNOMA: decida sozinho o que estudar a seguir para preencher os gaps acima e
aumentar sua autonomia, automelhoria e inteligência. Liste EXATAMENTE 6 queries de busca.
FORMATO OBRIGATÓRIO — cada uma em sua própria linha, exatamente assim:
🎯 QUERY: <query técnica específica e buscável em inglês>

Exemplo de formato:
🎯 QUERY: LangGraph stateful agent checkpointing Python production
🎯 QUERY: autonomous AI self-correction loop implementation Python

Síntese em português brasileiro — seja estratégico, arquitetural e acionável:"""


def _build_synthesis_prompt(clusters: dict[str, list[str]]) -> str:
    lines = []
    for domain, topics in clusters.items():
        lines.append(f"\n**{domain}** ({len(topics)} tópicos):")
        for t in topics[:6]:
            lines.append(f"  - {t}")
    return SYNTHESIS_CROSS_PROMPT.format(clusters_text="\n".join(lines))
