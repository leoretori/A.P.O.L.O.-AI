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
from src import factcheck
from src import graph
from src import spaced
from src.llm import KEEP_ALIVE, chat_resilient
from src.storage_models import _now as _now_utc
from src.topics import classify_sector
from src.web_search import web_research, fetch_page_text

logger = logging.getLogger(__name__)

# Teto de tokens da geração do learner — evita que o modelo leve "desande" e
# escreva até encher o contexto (o que estourava o timeout e travava o pipeline).
SUMMARY_MAX_TOKENS = int(os.getenv("SUMMARY_MAX_TOKENS", 600))
SYNTHESIS_MAX_TOKENS = int(os.getenv("SYNTHESIS_MAX_TOKENS", 1000))

# Reparo de sínteses cruas (E9): ledger append-only das tentativas que
# falharam. Sem ele, um item que o modelo não consegue re-sintetizar volta em
# TODA rodada, gastando 1 chamada de LLM por vez, para sempre.
REPAIR_LEDGER = os.getenv("REPAIR_LEDGER", "data/repair_attempts.jsonl")
MAX_REPAIR_TRIES = int(os.getenv("MAX_REPAIR_TRIES", 2))

from src.learner_types import (  # noqa: F401 (re-exporta p/ compat)
    FETCH_QUEUE_MAX, SYNTHESIS_EVERY, LLM_DOWN_BACKOFF, MAX_CONTENT_CHARS,
    PERSIST_TIMEOUT, VERIFY_SAMPLE_EVERY, CURRICULUM_RELEVANCE_MIN, CURRICULUM_MAX_WORDS,
    FetchedItem, LearnedItem,
    SUMMARIZE_PROMPT, SUMMARIZE_PROMPT_GERAL, GENERAL_CATEGORIES,
)
from src.learner_synthesis import (  # noqa: F401 (re-exporta p/ compat)
    _extract_self_queries, _cluster_topics, _build_synthesis_prompt,
)


def _parse_topic_lines(text: str) -> list[str]:
    """Extrai tópicos de uma lista gerada por LLM (1 por linha). Tira bullets/
    numeração/aspas e o preâmbulo típico ('Aqui estão...', 'Claro:'). Mantém só
    frases plausíveis (tem espaço, 6–120 chars)."""
    out: list[str] = []
    for line in (text or "").splitlines():
        s = re.sub(r"^[\s\-\*•\d\.\)#>]+", "", line).strip().strip("\"'`").strip()
        low = s.lower()
        if not (6 <= len(s) <= 120) or " " not in s:
            continue
        if low.startswith(("aqui", "claro", "segue", "abaixo", "estes", "esses")):
            continue
        out.append(s)
    return out[:15]


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
        profile=None,
    ):
        self.model = model
        # Cede a GPU às requisições do usuário (resposta interativa tem prioridade).
        self.gpu_gate = gpu_gate
        # Modelo dedicado à sumarização — pode ser menor/mais rápido (ex: codellama).
        # Definido via env SUMMARIZE_MODEL; cai para o modelo principal se ausente.
        self.summarize_model = summarize_model or os.getenv("SUMMARIZE_MODEL", "").strip() or model
        self.rag = rag
        self.knowledge_db = knowledge_db
        # P2.2: metas/projetos ativos (src/profile.py) ancoram o currículo
        # auto-dirigido — sem isto, `_replenish_curriculum` só sabia o que já
        # tinha estudado, não o que IMPORTA para o Leo agora. Opcional (None
        # funciona igual a antes — cai no comportamento só-por-novidade).
        self.profile = profile
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
        # Rotação de listas fixas esgotada (tudo já estudado na janela de RELEARN_DAYS)?
        # Um replenish gera tópicos NOVOS via LLM. Flag evita gerar em paralelo.
        self._replenishing = False

        # Serializa TODA inferência do learner (summarize + síntese + replenish).
        # O pipeline se diz "único consumidor do Ollama", mas a síntese (14b) e o
        # replenish rodavam via create_task EM PARALELO com o summarizer (3b) →
        # numa máquina 16GB CPU-only os dois modelos inferindo juntos travam tudo
        # (thrash de RAM/CPU) e TODO tópico estoura o timeout. O lock garante um de
        # cada vez — cada chamada roda a plena velocidade em vez de as duas patinarem.
        self._llm_lock = asyncio.Lock()

        # P2.1: amostra ~10% dos resumos salvos e audita contra a fonte (a fonte
        # só existe em memória NESTA sessão — `item.content` some depois do save).
        # Contador determinístico (não aleatório) — mesma disciplina do resto do
        # projeto: reproduzível, fácil de testar.
        self._verify_counter = 0

        # Filas do pipeline
        # (acessor público abaixo — quem mais fala com o Ollama, ex.: o harness de
        #  avaliação, pega ESTE lock para não voltar a rodar 14b+3b concorrente)
        self._fetch_queue: asyncio.Queue[FetchedItem] = asyncio.Queue(maxsize=FETCH_QUEUE_MAX)
        self._user_queue:  asyncio.Queue[str]         = asyncio.Queue()
        # Fila auto-dirigida: tópicos que o próprio A.P.O.L.O. decidiu estudar
        self._self_queue:  asyncio.Queue[str]         = asyncio.Queue(maxsize=24)

        # Tasks do pipeline
        self._tasks: list[asyncio.Task] = []
        # Tasks avulsas de fundo (save, síntese, recall, currículo) — precisam de
        # referência FORTE, senão o GC pode coletá-las no meio da execução (E8).
        self._bg_tasks: set[asyncio.Task] = set()
        # Ledger das tentativas de reparo (E9) — atributo p/ os testes isolarem.
        self.repair_ledger = REPAIR_LEDGER

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

    @property
    def llm_lock(self) -> asyncio.Lock:
        """Lock que serializa TODA inferência do learner. Exposto para que outro
        consumidor do Ollama (harness de avaliação) rode um-de-cada-vez com ele e
        não reintroduza o thrash 14b+3b que travava a máquina."""
        return self._llm_lock

    # ── Tasks de fundo ────────────────────────────────────────

    def _spawn(self, coro, *, name: str) -> asyncio.Task:
        """`create_task` com referência FORTE e exceção logada (E8).

        A doc do asyncio é explícita: o event loop guarda apenas uma referência
        FRACA à task — sem guardar a nossa, o coletor de lixo pode destruí-la no
        meio da execução. E uma exceção numa task solta nunca chega ao logger da
        app: some como "Task exception was never retrieved" no stderr cru, se
        tanto. Era exatamente o caminho do SAVE de cada conhecimento
        (`_save_and_record`) — este projeto já perdeu um mês de aprendizado para
        um except silencioso; o padrão aqui é o mesmo em outra roupa.
        """
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_task_done)
        return task

    def _maybe_synthesize(self) -> None:
        """Marco de síntese cross-domain: a cada `SYNTHESIS_EVERY` itens salvos.

        Um lugar só (E22): `learn_from_web` também incrementa `_saved_count`,
        mas não checava o marco — quando o Coder salvava o item de número N×20,
        a síntese daquele ciclo simplesmente não acontecia."""
        if self._saved_count and self._saved_count % SYNTHESIS_EVERY == 0:
            self._spawn(self._run_deep_synthesis(), name="deep-synthesis")

    def _bg_task_done(self, task: asyncio.Task) -> None:
        self._bg_tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(f"[learner] task de fundo '{task.get_name()}' falhou: "
                           f"{type(exc).__name__}: {exc}", exc_info=exc)

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

    def _effective_relearn_days(self, topic: str) -> int:
        """P2.7: janela de re-verificação MENOR que o padrão (RELEARN_DAYS) pra
        tópicos que merecem atenção mais cedo — setor volátil (tech que muda
        rápido, `topics.relearn_window_days`) OU ligado a uma meta/projeto
        ATIVO do perfil (reusa `_curriculum_relevance` do P2.3: mesma régua
        de 'conecta com o que importa agora'). Os dois cortam a janela; o
        menor vence — piso de 3 dias, EXCETO se RELEARN_DAYS estiver desligado
        (<=0) — desligado é desligado, não hesitamos."""
        from src.topics import relearn_window_days

        days = relearn_window_days(topic)
        if days <= 0:
            return days
        needs = self._active_needs_context()
        if needs and self._curriculum_relevance(topic, needs) >= CURRICULUM_RELEVANCE_MIN:
            days = max(1, days // 2)
        return max(3, days)

    def _already_known_sync(self, topic: str, url: str = "") -> bool:
        """Núcleo síncrono de `_already_known` (roda em thread)."""
        if self._norm(topic) in self._skip_session:
            return True
        if not self.db:
            return False
        relearn_days = self._effective_relearn_days(topic)
        if url and self.db.is_url_studied(url, relearn_days=relearn_days):
            return True
        return self.db.is_topic_studied(topic, relearn_days=relearn_days)

    async def _already_known(self, topic: str, url: str = "") -> bool:
        """Já estudado (por tópico OU por URL) ou desistido nesta sessão? Vale
        para TODOS os agentes — antes só o doc_agent checava URL.

        Vai para thread (E24): era a única consulta SQLite SÍNCRONA dentro do
        event loop em todo o pipeline — os fetchers a chamam por tópico, e um
        banco lento (ou um lock do SQLite) travaria o loop inteiro."""
        return await asyncio.to_thread(self._already_known_sync, topic, url)

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
        # Tasks avulsas NÃO são canceladas: cancelar um `_save_and_record` no
        # meio perderia o conhecimento já sintetizado. Esperamos as que estão
        # em voo terminarem (com teto — parar não pode travar o app).
        if self._bg_tasks:
            pendentes = list(self._bg_tasks)
            logger.info(f"[learner] esperando {len(pendentes)} task(s) de fundo terminarem…")
            await asyncio.wait(pendentes, timeout=30)
        self.stats.update({"current_topic": "", "current_source": "", "agents": []})
        logger.info("A.P.O.L.O. Learner PARADO")

    async def study_now(self, topic: str) -> dict:
        """Estuda tópico imediatamente — injeta na fila de usuário com prioridade."""
        logger.info(f"[study_now] {topic}")
        # E23: passa pelo MESMO dedup in-flight dos fetchers — dois cliques
        # rápidos (ou um clique junto com o pipeline pegando o tema) estudavam
        # o mesmo tópico 2×, gastando duas chamadas de LLM para o mesmo texto.
        if not self._reserve(topic):
            return {"ok": False, "topic": topic, "error": "já estou estudando este tópico"}
        self.stats["current_topic"] = topic
        try:
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
            # E23: conta como conhecimento salvo, como qualquer outro caminho —
            # senão o painel e o marco de síntese ignoram o que o Leo pediu.
            self._saved_count += 1
            self._maybe_synthesize()
            self.stats["current_topic"] = ""
            return {"ok": True, "topic": topic, "url": url, "summary": summary,
                    "agent": "study_now", "time": item.timestamp}
        finally:
            self._release(topic)

    @staticmethod
    def _looks_raw(summary: str) -> bool:
        """Parece conteúdo CRU salvo por timeout antigo (não uma síntese)?

        Só "não tem `##`" era severo demais (E9): o 1.5B escreve sínteses
        válidas sem cabeçalho, e elas eram marcadas como cruas PARA SEMPRE —
        cada rodada de reparo gastava uma chamada de LLM nelas, e se a
        re-síntese também viesse sem `##`, contava como falha e voltava na
        rodada seguinte. Moto-perpétuo de custo. Agora qualquer sinal de
        ESTRUTURA vale: cabeçalho, lista, negrito ou vários parágrafos."""
        s = (summary or "").strip()
        if len(s) < 300:
            return False
        if "##" in s or "**" in s:
            return False
        linhas = [ln.strip() for ln in s.splitlines() if ln.strip()]
        if sum(1 for ln in linhas if ln.startswith(("- ", "* ", "• "))) >= 2:
            return False
        if s.count("\n\n") >= 2:                 # 3+ parágrafos = texto organizado
            return False
        return True

    @staticmethod
    def _repair_key(item_id, topic: str) -> str:
        """Chave da tentativa de reparo: id E tópico. Só o id não serve — ids
        são sequenciais por banco, então o "1" de um banco casaria com o "1" de
        outro (foi o que embaralhou os testes)."""
        return f"{item_id}:{re.sub(r'\\s+', ' ', (topic or '').strip().lower())[:60]}"

    def _repair_giveups(self) -> set[str]:
        """Itens que já falharam `MAX_REPAIR_TRIES` vezes no reparo (E9)."""
        from src.jsonl_history import read_entries
        tentativas: dict[str, int] = {}
        for e in read_entries(self.repair_ledger, limit=5000):
            key = e.get("key") or str(e.get("id"))
            tentativas[key] = tentativas.get(key, 0) + 1
        return {k for k, n in tentativas.items() if n >= MAX_REPAIR_TRIES}

    def _record_repair_attempt(self, item_id, topic: str) -> None:
        """Anota a tentativa fracassada no ledger append-only (E9)."""
        if item_id is None:
            return
        try:
            from src.jsonl_history import append_entry
            append_entry(self.repair_ledger,
                         {"key": self._repair_key(item_id, topic),
                          "id": str(item_id), "topic": topic[:80]})
        except Exception as e:
            logger.debug(f"[repair] não consegui registrar a tentativa: {e}")

    async def repair_raw_summaries(self, limit: int = 8) -> dict:
        """Repara conhecimentos salvos CRUS (timeouts antigos que gravaram o
        texto truncado como 'síntese'): re-sintetiza a partir do próprio texto
        salvo, com o template certo da categoria, e atualiza in-place (log
        SQLite + índice RAG). Roda em background — 1 chamada de LLM por item."""
        if not self.db:
            return {"ok": False, "error": "sem banco"}
        rows = await asyncio.to_thread(self.db.get_learning_history, 300)
        desistidos = self._repair_giveups()
        candidatos = [r for r in rows
                      if self._looks_raw(r.get("summary", ""))
                      and self._repair_key(r.get("id"), r.get("topic", "")) not in desistidos]
        raw_rows = candidatos[:limit]
        repaired, failed = 0, 0
        for r in raw_rows:
            summary = await self._summarize(
                r["topic"], r["summary"], r.get("category") or "web_search")
            if not summary or self._looks_raw(summary):
                failed += 1
                # E9: registra a tentativa; depois de MAX_REPAIR_TRIES o item
                # sai da fila para sempre em vez de queimar 1 chamada de LLM
                # por rodada, para sempre.
                self._record_repair_attempt(r.get("id"), r.get("topic", ""))
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
                    # warning (não debug): foi um except+debug igual a este que
                    # escondeu o NameError do fetch_page_text por meses ("buscados:0",
                    # ver lição na memória). Erro de código não pode sumir em silêncio.
                    logger.warning(f"[{agent.name}] priority fetch error: {e}")
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
                    if (await self._already_known(topic, url_hint)
                            or not self._reserve(topic)):
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
                logger.debug(f"[{agent.name}] fetch timeout")   # esperado (rede lenta)
            except Exception as e:
                # warning: este é o caminho exato do bug original (fetch_page_text
                # NameError, engolido aqui em debug, parou o aprendizado sem sinal).
                logger.warning(f"[{agent.name}] fetch error: {e}")
            finally:
                agent.active = False
                agent.current_topic = ""

            # Pequena pausa entre fetches do mesmo agente
            await asyncio.sleep(3)

    async def _fetch_and_enqueue_search(self, topic: str, category: str, agent_name: str) -> None:
        # Anti-duplicação: não re-estuda tópicos de rotação já aprendidos. Perguntas do
        # usuário e o currículo auto-dirigido podem repetir de propósito, então passam.
        if (category not in ("user_question", "self_directed")
                and await self._already_known(topic)):
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
            logger.warning(f"[search] {topic[:40]}: {e}")
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
            # P2.1: 1 em cada VERIFY_SAMPLE_EVERY resumos é auditado contra a
            # fonte AQUI — é a última chance, `item.content` não é persistido.
            self._verify_counter += 1
            verified = None
            if self._verify_counter % VERIFY_SAMPLE_EVERY == 0:
                verified = await self._verify_summary(summary, item.content)
                if verified == "failed":
                    logger.warning(f"[verify] resumo pode não ser fiel à fonte: "
                                   f"{item.topic[:50]}")
            learned = LearnedItem(
                topic=item.topic, url=item.url, summary=summary,
                category=item.category, agent_name=item.agent_name,
                verified=verified,
            )
            # Passa para o saver via atributo (evita mais uma fila)
            self._spawn(self._save_and_record(learned), name="save-and-record")
        finally:
            self._active_summarizing = ""

    async def _save_worker(self) -> None:
        """Worker de controle — mantém o loop vivo, emite status e DETECTA STALL.
        Um pipeline que para de progredir em silêncio foi exatamente o bug 'estudou
        45 e travou'; aqui ele grita (WARNING + 1 notificação) com o diagnóstico."""
        prev_saved = prev_fetched = -1
        stalled_cycles = 0
        stall_notified = False
        cycle = 0
        while self.running:
            await asyncio.sleep(30)
            if not self.running:
                break
            try:
                cycle += 1
                q = self._fetch_queue.qsize()
                logger.info(
                    f"A.P.O.L.O. pipeline — fila:{q} | salvos:{self._saved_count} | "
                    f"buscados:{self._fetched_count}"
                )
                # M8 8.1: recall ativo periódico (~10 min). Só RAG+DB, sem LLM → não
                # concorre com o summarizer; re-enfileira o que o A.P.O.L.O. esqueceu.
                if cycle % 20 == 0:
                    self._spawn(self._run_active_recall(), name="active-recall")
                # Sem progresso (nem salvou, nem buscou) desde o último ciclo?
                no_progress = (self._saved_count == prev_saved and
                               self._fetched_count == prev_fetched)
                prev_saved, prev_fetched = self._saved_count, self._fetched_count
                if no_progress:
                    stalled_cycles += 1
                else:
                    stalled_cycles = 0
                    stall_notified = False
                # ~1 min sem progresso e a fila auto-dirigida vazia → provável ROTAÇÃO
                # ESGOTADA (tudo já estudado). Gera currículo novo via LLM p/ destravar
                # (não espera os 2 min do WARNING — recuperação é melhor que só avisar).
                # Reincide a cada ~1 min enquanto parado (se uma geração vier vazia, tenta
                # de novo); o flag _replenishing evita sobreposição.
                if (stalled_cycles >= 2 and stalled_cycles % 2 == 0
                        and self._self_queue.empty()
                        and not self._llm_down and not self._replenishing):
                    logger.info("[curriculo] rotação parece esgotada — gerando temas novos…")
                    self._spawn(self._replenish_curriculum(), name="replenish-curriculum")
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
            except Exception as e:
                # O PRÓPRIO monitor de stall não pode morrer em silêncio: sem este
                # guard, uma exceção aqui matava a task pra sempre e ninguém saberia
                # (uma exceção não tratada numa asyncio.Task não passa pelo logger da
                # app — só aparece, se muito, como "Task exception was never
                # retrieved" no stderr cru, quando a task for coletada).
                logger.warning(f"[pipeline] monitor de stall falhou (segue vivo): {e}")

    async def _save_and_record(self, item: LearnedItem) -> None:
        # M8 8.2: guarda a síntese anterior deste tópico (se houver) p/ comparar fatos.
        old_summary = None
        if self.db:
            try:
                old_summary = await asyncio.to_thread(self.db.get_topic_summary, item.topic)
            except Exception:
                old_summary = None
        try:
            await self._persist(item)
            self._record_activity(item)
            self._saved_count += 1
            await self._ensure_review_scheduled(item.topic)   # M8 8.1: agenda revisão
            if old_summary:                                    # M8 8.2: contradição?
                self._check_fact_drift(item.topic, old_summary, item.summary)
            await self._link_related(item.topic, item.summary)  # M8 8.3: grafo
        finally:
            # Só aqui o tópico sai do in-flight: a partir de agora ele consta como
            # "estudado" no banco, então os fetchers não o pegam de novo.
            self._release(item.topic)

        self._maybe_synthesize()

    async def _link_related(self, topic: str, summary: str) -> None:
        """M8 8.3: liga o tópico recém-aprendido aos tópicos recentes com que ele
        MAIS compartilha conceitos → arestas do grafo de conhecimento. Sem LLM."""
        if not self.db or not summary:
            return
        try:
            history = await asyncio.to_thread(self.db.get_learning_history, 40)
        except Exception:
            return
        scored = []
        for h in history:
            other = h.get("topic")
            if not other or other == topic:
                continue
            s = graph.strength(summary, h.get("summary") or "")
            if s >= 0.1:                        # limiar mínimo de conexão
                scored.append((s, other, graph.shared_concepts(summary, h.get("summary") or "")))
        scored.sort(key=lambda x: x[0], reverse=True)
        for s, other, shared in scored[:5]:     # liga aos 5 mais relacionados
            try:
                await asyncio.to_thread(self.db.add_edge, topic, other, s, shared)
            except Exception:
                pass

    def _check_fact_drift(self, topic: str, old: str, new: str) -> None:
        """M8 8.2: re-estudou um tópico e uma DATA mudou → possível contradição.
        Avisa o usuário (não bloqueia o aprendizado). Sem LLM."""
        try:
            d = factcheck.numeric_drift(old, new)
            if d["drift"]:
                logger.info(f"[factcheck] deriva em '{topic[:40]}': "
                            f"{d['dropped']} → {d['added']}")
                if self.db:
                    self.db.add_notification(
                        f"⚠️ Fato mudou em '{topic[:50]}' — {d['note']}", kind="info")
        except Exception as e:
            logger.debug(f"[factcheck] {topic[:40]}: {e}")

    # ── Repetição espaçada + recall ativo (M8 8.1) ────────────
    async def _ensure_review_scheduled(self, topic: str) -> None:
        """Ao aprender um tópico, cria sua agenda de revisão (1ª revisão ~1 dia).
        Não sobrescreve uma agenda existente (re-estudo não zera o progresso SR)."""
        if not self.db or not topic:
            return
        try:
            existing = await asyncio.to_thread(self.db.get_review, topic)
            if existing:
                return
            st = spaced.review(spaced.initial_state(), 4)   # 1º acerto → 1 dia
            await asyncio.to_thread(
                self.db.upsert_review, topic, st["ease"], st["interval"],
                st["reps"], st["lapses"], spaced.next_due(st, _now_utc()), _now_utc())
        except Exception as e:
            logger.debug(f"[review] agendar {topic[:40]}: {e}")

    def _recall_strength(self, topic: str) -> tuple[float, bool]:
        """Auto-teste SEM LLM: quão bem ainda lembra do tópico? = força do melhor
        acerto no recall da memória (RAG). Sem acerto = esqueceu."""
        try:
            hits = self.rag.recall(topic, 3) if self.rag else []
        except Exception:
            hits = []
        if not hits:
            return 0.0, False
        top = hits[0].get("relevance")
        return (float(top) if isinstance(top, (int, float)) else 0.5), True

    async def _run_active_recall(self, limit: int = 5) -> None:
        """Pega tópicos vencidos, se auto-testa (recall), reprograma via SM-2 e
        RE-ENFILEIRA os que esqueceu (self_directed ignora o RELEARN_DAYS)."""
        if not self.db:
            return
        try:
            due = await asyncio.to_thread(self.db.due_reviews, _now_utc(), limit)
        except Exception:
            return
        forgot = []
        for r in due:
            topic = r["topic"]
            score, has_hit = self._recall_strength(topic)
            quality = spaced.quality_from_recall(score, has_hit)
            st = spaced.review(r, quality)
            try:
                await asyncio.to_thread(
                    self.db.upsert_review, topic, st["ease"], st["interval"],
                    st["reps"], st["lapses"], spaced.next_due(st, _now_utc()), _now_utc())
            except Exception:
                pass
            if quality < spaced.PASS_THRESHOLD:
                forgot.append(topic)
        # Esquecidos voltam DIRETO para a fila auto-dirigida (sem o filtro
        # is_topic_studied de _enqueue_self_studies — o tópico JÁ foi estudado, é
        # de propósito re-estudá-lo). O fetch self_directed ignora o RELEARN_DAYS.
        enfileirados = 0
        for topic in forgot:
            if self._self_queue.full():
                break
            try:
                self._self_queue.put_nowait(topic)
                enfileirados += 1
            except asyncio.QueueFull:
                break
        if enfileirados:
            self._next_studies = forgot[:enfileirados]
            logger.info(f"[recall] revisão: {len(due)} testados, "
                        f"{enfileirados} esquecidos re-enfileirados")

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
        self._maybe_synthesize()          # E22: este caminho pulava o marco
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
            async with self._llm_lock:          # não concorre com o summarizer (3b)
                # Usa o modelo LEVE (mesmo do summarizer), NÃO o pesado: em CPU de
                # 16GB, carregar o 7B aqui deixava o 1.5B + 7B residentes ao mesmo
                # tempo → swap → o summarizer estourava o timeout e o estudo TRAVAVA.
                # Mantendo tudo do learner no 1.5B, o pesado nunca entra em cena no
                # fundo (só no Inteligente/Profundo que o usuário dispara).
                synthesis = await asyncio.wait_for(
                    asyncio.to_thread(
                        chat_resilient, self.summarize_model,
                        [{"role": "user", "content": prompt}],
                        keep_alive=KEEP_ALIVE,
                        options={"num_predict": SYNTHESIS_MAX_TOKENS},   # bounded (ver _summarize)
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
            logger.warning(f"[synthesizer] Erro: {type(e).__name__}: {e}")
        finally:
            self._synthesis_agent.active = False
            self._synthesis_agent.current_topic = ""

    def _active_needs_context(self) -> str:
        """P2.2: metas/projetos ativos (src/profile.py) — a parte 'por
        NECESSIDADE' do currículo. Vazio se não há perfil ou nada nessas
        categorias (o comportamento antigo, só-por-novidade, continua valendo)."""
        profile = getattr(self, "profile", None)
        if not profile:
            return ""
        try:
            groups = profile.by_category()
        except Exception:
            return ""
        itens = [f.get("fact", "") for cat in ("goal", "project") for f in groups.get(cat, [])]
        itens = [i for i in itens if i]
        return "; ".join(itens[:15])[:800]

    def _interest_corpus(self) -> str:
        """P2.3: o texto contra o qual um tópico AUTOGERADO é julgado antes de
        entrar na fila — SÓ metas/projetos/preferências/valores do PERFIL
        (sinal curado, explícito). Tentativa inicial incluía o histórico de
        tópicos já estudados como corpus também — descartada depois de medir:
        rejeitava diversidade LEGÍTIMA (ex.: "Filosofia estoica" reprovado só
        por não compartilhar palavra com "Docker"/"Redis" recém-estudados),
        indo contra o próprio objetivo do currículo, que É diversidade, não
        repetição temática. Perfil vazio → "" → `_curriculum_relevance` não
        filtra por relevância (só a verbosidade, sempre ativa, continua)."""
        parts = [self._active_needs_context()]
        profile = getattr(self, "profile", None)
        if profile:
            try:
                groups = profile.by_category()
                for cat in ("preference", "value"):
                    parts.extend(f.get("fact", "") for f in groups.get(cat, []))
            except Exception:
                pass
        return " ".join(p for p in parts if p)

    def _curriculum_relevance(self, topic: str, corpus: str) -> float:
        """0..1 — fração do tópico que se conecta ao corpus de interesse.
        SEM sinal pra julgar (corpus vazio — perfil sem metas/projetos/
        preferências/valores) devolve 1.0 — não filtra no cold start; isso não
        é 'todo tópico é relevante', é 'não temos como saber ainda'."""
        from src.rerank import lexical_overlap, tokenize

        corpus_tokens = tokenize(corpus)
        if not corpus_tokens:
            return 1.0
        topic_tokens = tokenize(topic)
        if not topic_tokens:
            return 0.0
        return lexical_overlap(topic_tokens, corpus)

    @staticmethod
    def _curriculum_too_verbose(topic: str) -> bool:
        """P2.3: heurística SEMPRE ativa (não depende de perfil) pro padrão
        real de deriva visto em produção (2026-07-15) — o LLM do currículo
        compondo jargão tipo 'Otimização de infraestruturas urbanas
        inteligentes com Machine Learning' (8 palavras) ou pior, 'Desenvolvimento
        e implementação da IA aplicada à gestão das águas potáveis urbanas
        resilientes' (12). Tópicos genuínos medidos são frases curtas — 'Filosofia
        estoica', 'Sistemas distribuídos' (2 palavras). Limiar com folga entre
        os dois grupos, não ajustado fino demais de propósito."""
        return len((topic or "").split()) > CURRICULUM_MAX_WORDS

    async def _replenish_curriculum(self) -> None:
        """Rotação de listas fixas ESGOTADA (tudo já estudado na janela) e a fila
        auto-dirigida vazia? Gera tópicos NOVOS via LLM a partir do que já sabe e
        os injeta na fila. Sem isto, com as listas esgotadas o pipeline fica em
        `buscados:0` para sempre (o famoso 'não está conseguindo estudar').

        P2.2: quando há metas/projetos ativos no perfil, o currículo passa a
        ser dirigido por NECESSIDADE (o que ajuda o Leo agora), não só por
        novidade (o que ainda não foi estudado) — as duas coisas convivem no
        mesmo prompt, sem perder a exploração geral."""
        if self._replenishing or not self.db:
            return
        self._replenishing = True
        try:
            history = await asyncio.to_thread(self.db.get_learning_history, 40)
            # "Síntese #N" é meta-informação do processo, não tema estudado: no
            # prompt do currículo o modelo lia os próprios números como assunto
            # e gerava auto-queries sobre eles (E18 — a clusterização já
            # filtrava; aqui não filtrava).
            from src.nanollm.distill import is_meta_item
            conhecidos = [h.get("topic", "") for h in history
                          if h.get("topic") and not is_meta_item(h)]
            amostra = "; ".join(conhecidos[:30])[:1500]
            needs = self._active_needs_context()
            needs_block = (
                f"\n\nMetas e projetos ativos do Leo agora: {needs}\n"
                "PRIORIZE tópicos que ajudem diretamente essas metas/projetos — o "
                "resto pode ser exploração geral (ciência, história, saúde, arte...)."
                if needs else
                "\n\nMisture tecnologia e conhecimento geral (ciência, história, "
                "saúde, arte...)."
            )
            prompt = (
                "Sou um currículo de autoaprendizado contínuo. Já estudei, entre outros:\n"
                f"{amostra}"
                f"{needs_block}\n\n"
                "Liste 12 tópicos NOVOS e ESPECÍFICOS que eu ainda não estudei, para "
                "aprofundar ou expandir esse conhecimento. "
                "Um por linha, sem numeração, sem explicação."
            )
            if self.gpu_gate:
                await self.gpu_gate.wait_for_idle()
            async with self._llm_lock:          # não concorre com summarize/síntese
                out = await asyncio.wait_for(
                    asyncio.to_thread(
                        chat_resilient, self.summarize_model,
                        [{"role": "user", "content": prompt}], keep_alive=KEEP_ALIVE,
                    ),
                    timeout=90.0,
                )
            topics = _parse_topic_lines(out)
            before = self._self_queue.qsize()
            self._enqueue_self_studies(topics)
            added = self._self_queue.qsize() - before
            logger.info(f"[curriculo] rotação esgotada → LLM gerou {len(topics)} "
                        f"temas, {added} novos entraram na fila")
            if self.db and added:
                try:
                    self.db.add_notification(
                        f"🌱 Currículo renovado: {added} temas novos para estudar",
                        kind="info")
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[curriculo] replenish falhou: {type(e).__name__}: {e}")
        finally:
            self._replenishing = False

    def _enqueue_self_studies(self, queries: list[str]) -> None:
        """Injeta na fila auto-dirigida os tópicos que o A.P.O.L.O. decidiu estudar.

        P2.3: antes de enfileirar, cada tópico passa pelo filtro de deriva —
        pontua a conexão com o que já se sabe ser do interesse do Leo (metas/
        projetos/preferências + histórico de estudo) e descarta o que não bate
        com NADA disso. Ataca o padrão real visto em produção (2026-07-15):
        o LLM do currículo divagando pra "Otimização de infraestruturas urbanas
        inteligentes com Machine Learning" — bem-formado, mas sem nenhuma
        conexão com o que o Leo realmente estuda."""
        if not queries:
            return
        corpus = self._interest_corpus()
        added, dropped = [], []
        for q in queries:
            if self._self_queue.full():
                break
            # Evita re-estudar o que já sabe. As queries são TÓPICOS (não URLs), então
            # a checagem correta é is_topic_studied — antes usava is_url_studied, que
            # nunca casava e fazia o A.P.O.L.O. re-estudar tópicos conhecidos.
            if self.db and self.db.is_topic_studied(q):
                continue
            if self._curriculum_too_verbose(q):
                dropped.append(q)
                continue
            if self._curriculum_relevance(q, corpus) < CURRICULUM_RELEVANCE_MIN:
                dropped.append(q)
                continue
            try:
                self._self_queue.put_nowait(q)
                added.append(q)
            except asyncio.QueueFull:
                break
        if added:
            self._next_studies = added
            logger.info(f"[auto-curriculum] 🎯 A.P.O.L.O. decidiu estudar: {added}")
        if dropped:
            logger.info(f"[curriculo] filtro de deriva descartou {len(dropped)}: "
                        f"{dropped[:5]}")

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
            async with self._llm_lock:          # 1 inferência do learner por vez
                out = await asyncio.wait_for(
                    asyncio.to_thread(
                        chat_resilient, self.summarize_model,
                        [{"role": "user", "content": prompt}],
                        keep_alive=KEEP_ALIVE,
                        # LIMITA a geração: sem teto, o 1.5B às vezes DESANDA e escreve
                        # até encher o contexto (milhares de tokens) → estoura os 120s
                        # → a thread zumbi segura o lock do motor → pipeline TRAVA. Um
                        # resumo cabe folgado em ~600 tokens.
                        options={"num_predict": SUMMARY_MAX_TOKENS},
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

    async def _verify_summary(self, summary: str, source: str) -> str | None:
        """P2.1: audita o resumo contra a FONTE crua (ainda em memória nesta
        sessão) — 'verified'/'failed'/None (indisponível/inconclusivo, nunca
        derruba o pipeline). Mesma disciplina de lock/gate/timeout do
        `_summarize` — não pode competir com ele pelo motor."""
        try:
            if self.gpu_gate:
                await self.gpu_gate.wait_for_idle()
            prompt = factcheck.GROUNDEDNESS_PROMPT.format(
                source=source[:2000], summary=summary[:1000])
            async with self._llm_lock:
                out = await asyncio.wait_for(
                    asyncio.to_thread(
                        chat_resilient, self.summarize_model,
                        [{"role": "user", "content": prompt}],
                        keep_alive=KEEP_ALIVE, options={"num_predict": 4},
                    ),
                    timeout=60.0,
                )
            return factcheck.parse_groundedness(out)
        except Exception as e:
            logger.debug(f"[verify] falhou (segue sem marcar): {e}")
            return None

    # ── Persistência ──────────────────────────────────────────

    async def _persist(self, item: LearnedItem) -> None:
        # Higiene de ingestão: não persiste lixo/injeção em NENHUM dos três destinos
        # (relacional, base FTS, memória semântica). Um item ruim aqui volta como
        # "📚 memória" na recall e entra no prompt do chat. Ver src/content_hygiene.
        from src.content_hygiene import is_ingestible
        _ok, _motivo = is_ingestible(item.topic, item.summary or "")
        if not _ok:
            logger.info(f"[learner] ingestão rejeitada ({_motivo}): {item.topic[:60]}")
            return
        tasks = []
        if self.db:
            tasks.append(asyncio.to_thread(
                self.db.save_learned_topic,
                item.topic, item.url, item.summary[:2000], item.category,
                item.verified,
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
                    {"verified": item.verified or "unchecked"},
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


