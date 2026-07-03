"""A.P.O.L.O. — Agente Pessoal de Operações, Lógica e Otimização."""

import asyncio
import os
import re
import sys
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware   # #3
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import ollama as ollama_client

# Carrega o .env ANTES de importar os módulos src — vários deles leem variáveis de
# ambiente em tempo de import (ex.: KEEP_ALIVE/perfil de hardware em src.llm).
load_dotenv()

from src.rag import RAGManager
from src.storage import DatabaseManager
from src.executor import CodeExecutor
from src.learner import LearningEngine
from src.research import DeepResearchAgent
from src.reviewer import CodeReviewAgent
from src.ingest import DocumentIngestor
from src.curator import MemoryCurator
from src.profile import UserProfile
from src.gpu_gate import GpuGate
from src.llm import (
    KEEP_ALIVE, KEEP_ALIVE_HEAVY, stream_chat, warmup,
    ollama_breaker_state, chat_resilient,
)
from src.prompts import (
    SYSTEM_PROMPT, GENERATE_PROMPT, PERSONAL_SECTION,
    MEMORY_SECTION, KNOWLEDGE_SECTION, WEB_SECTION,
    FIX_PROMPT, SESSION_TITLE_PROMPT, FACT_EXTRACT_PROMPT,
    CONVERSATION_SUMMARY_PROMPT, CONVERSATION_SUMMARY_SECTION,
    AGENT_INSTRUCTION, AGENT_MEMORY_SECTION, AGENT_SELFEVAL_PROMPT,
    CODER_SYSTEM, CODER_DOCTRINE, CODER_TREE_SECTION, CODER_PLAN_PROMPT,
    CODER_REFLECT_PROMPT, COMMIT_MSG_PROMPT,
)
from src.coder import CoderWorkspace, extract_fenced, make_diff, compact_messages
from src.lessons import LessonMemory
from src.episodic import index_session as _index_episodic
from src.project_memory import ProjectMemory, analyze_project as _analyze_project
from src.system_cache import get as _syscache_get, put as _syscache_put, invalidate as _syscache_inv
from src.query_cache import (                        # #1 #2
    recall_get as _qcache_recall_get, recall_put as _qcache_recall_put,
    fts_get as _qcache_fts_get, fts_put as _qcache_fts_put,
    invalidate_all as _qcache_inv, stats as _qcache_stats,
)
from src.utils import extract_code, extract_explanation, sanitize_request
from src.model_select import pick_chat_model, pick_vision_model
from src.routing import is_complex
from src.web_search import web_research

# Windows: o console cp1252 não encoda emoji (☀️, 🎯, ✓...) e quebra prints/logs.
# Força UTF-8 nos streams para o A.P.O.L.O. rodar em qualquer terminal.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# #4 Logging otimizado: app fica em INFO, libs barulhentas em WARNING.
# httpx/httpcore geram 1 log por requisição de rede — em produção são dezenas/min.
# LOG_LEVEL=DEBUG restaura tudo para debug.
_LOG_LEVEL = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(level=_LOG_LEVEL, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
for _noisy in ("httpx", "httpcore", "watchfiles", "chromadb.telemetry"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
# Modelo dedicado à sumarização do aprendizado — pode ser menor/mais rápido.
# Se vazio, usa o modelo principal. Ex: SUMMARIZE_MODEL=codellama:latest
SUMMARIZE_MODEL = os.getenv("SUMMARIZE_MODEL", "").strip() or MODEL
# Modelo leve para o chat do dia a dia — resposta rápida na CPU. O modelo
# principal (14b) fica reservado para Pesquisa Profunda / Code Review.
# Se vazio, é resolvido no startup (melhor modelo leve instalado → senão MODEL).
CHAT_MODEL = os.getenv("CHAT_MODEL", "").strip()
# Ordem de preferência ao auto-escolher o modelo de chat (mais leve primeiro).
LIGHT_MODEL_PREFERENCE = [
    "qwen2.5-coder:3b", "qwen2.5:3b", "llama3.2:3b", "phi3:mini",
    "gemma2:2b", "qwen2.5-coder:7b", "codellama:latest",
]
# Modelos "rápidos" (≤3B) — se o chat já usa um destes, não sugerimos baixar outro.
FAST_MODELS = {"qwen2.5-coder:3b", "qwen2.5:3b", "llama3.2:3b", "phi3:mini", "gemma2:2b"}
# Nº de mensagens do histórico enviadas ao LLM. Na CPU, histórico grande = prefill
# mais lento; 12 mantém boa memória de conversa sem inflar a latência. Configurável.
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 12))
# Modo Agente (ReAct iterativo): nº máximo de rodadas pensar→executar e de
# tentativas de auto-correção de erro antes de responder com o que tem.
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", 5))
MAX_AGENT_FIXES = int(os.getenv("MAX_AGENT_FIXES", 2))
# Modo Coder ("Claude Code" interno): nº máximo de passos ler/escrever/rodar.
MAX_CODER_STEPS = int(os.getenv("MAX_CODER_STEPS", 12))
# Orçamento de contexto do loop do Coder (chars). Acima disso, observações antigas
# são compactadas — evita estourar num_ctx=8192 e "esquecer" a tarefa/plano.
CODER_CTX_CHARS = int(os.getenv("CODER_CTX_CHARS", 20000))
# Reflexão pós-tarefa do Coder: extrai 1 lição e guarda na memória de lições
# (data/lessons.db) — injetada nas próximas tarefas parecidas. CODER_REFLECT=0 desativa.
CODER_REFLECT = os.getenv("CODER_REFLECT", "1") not in ("0", "false", "False")
# Cache do baseline da guarda de regressão: se a suíte foi medida há pouco e nada
# mudou por fora, o Coder não re-roda a suíte INTEIRA no início de cada tarefa
# (na CPU isso economiza minutos por tarefa). Invalidado por qualquer mudança
# feita fora do loop (terminal, apagar/mover/substituir, undo, troca de pasta).
CODER_BASELINE_TTL = int(os.getenv("CODER_BASELINE_TTL", 900))
_coder_baseline_cache: dict[str, tuple[bool, float]] = {}


def _invalidate_baseline() -> None:
    """Workspace mudou fora do loop do Coder → baseline de testes não vale mais."""
    _coder_baseline_cache.clear()
# Auto-avaliação: após rascunhar a resposta, o agente critica e refina a si mesmo (1 passe).
AGENT_SELF_EVAL = os.getenv("AGENT_SELF_EVAL", "1") not in ("0", "false", "False", "")
# Memória de conversas longas: acima de SUMMARY_TRIGGER msgs, resume as antigas;
# regenera o resumo a cada SUMMARY_STALE mensagens novas (em background).
SUMMARY_TRIGGER = int(os.getenv("SUMMARY_TRIGGER", 16))
SUMMARY_STALE = int(os.getenv("SUMMARY_STALE", 8))
LEARNING_INTERVAL = int(os.getenv("LEARNING_INTERVAL", 180))
# Tempo máximo esperando o Supabase antes de responder sem ele (não atrasa o 1º token).
KNOWLEDGE_TIMEOUT = float(os.getenv("KNOWLEDGE_TIMEOUT", 4))
# Limite de caracteres do contexto RAG injetado (corta o prefill na CPU).
RAG_CTX_CHARS = int(os.getenv("RAG_CTX_CHARS", 1200))
# Auto-roteamento: perguntas complexas usam o 14b sozinhas (sem o usuário ligar o toggle).
AUTO_SMART = os.getenv("AUTO_SMART", "1") not in ("0", "false", "False", "")
# Recall semântico no chat: quantas memórias buscar, quantas usar, corte de relevância e tamanho.
MEMORY_RECALL_N = int(os.getenv("MEMORY_RECALL_N", 6))   # busca mais candidatos para rerank
MEMORY_TOP = int(os.getenv("MEMORY_TOP", 3))
MEMORY_MIN_RELEVANCE = float(os.getenv("MEMORY_MIN_RELEVANCE", 0.18))  # limiar levemente menor
MEMORY_SNIPPET = int(os.getenv("MEMORY_SNIPPET", 400))                 # snippets mais longos
# Auto-pesquisa na web quando não há memória relevante (lacuna de conhecimento).
# Evita resposta vaga — busca informação real antes de responder.
AUTO_WEB_ON_GAP = os.getenv("AUTO_WEB_ON_GAP", "1") not in ("0", "false", "False")
# Contexto rico (≥N memórias relevantes) → upgrade automático para 14B para síntese mais profunda.
MEMORY_RICH_14B = int(os.getenv("MEMORY_RICH_14B", 2))
# Self-eval no chat: após responder, o A.P.O.L.O. critica e refina a própria resposta.
# Só ativo quando já usando 14b (evita dobrar latência no modelo leve).
# Desative com CHAT_SELF_EVAL=0.
CHAT_SELF_EVAL = os.getenv("CHAT_SELF_EVAL", "1") not in ("0", "false", "False")
# Rate limiting: máximo de requisições por endpoint por janela de 60s.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT", "1") not in ("0", "false", "False")
_rate_windows: dict[str, list] = defaultdict(list)
_RATE_LIMITS = {"/api/chat": 40, "/api/research": 15, "/api/agent": 20,
                "/api/orchestrate": 10, "default": 80}
# Mensagens curtas (sim/não/ok/continue) → modelo leve sempre, sem recall caro.
# Número máximo de caracteres para considerar mensagem "curta".
SHORT_MSG_CHARS = int(os.getenv("SHORT_MSG_CHARS", 40))
# Idle learning: se o usuário ficar inativo por IDLE_TRIGGER segundos e o
# aprendizado estiver parado, o A.P.O.L.O. o inicia automaticamente.
# 0 = desativado. Padrão 600 (10 min). GpuGate já preempta o learner quando
# o usuário mandar uma mensagem — não há conflito.
IDLE_TRIGGER = int(os.getenv("IDLE_TRIGGER", 600))
# API LAN: token de acesso para expor a API na rede local (vazio = sem autenticação).
API_TOKEN = os.getenv("API_TOKEN", "").strip()
# Histórico de benchmark em memória (últimos N runs)
_benchmark_history: list[dict] = []
_BENCHMARK_HISTORY_MAX = int(os.getenv("BENCHMARK_HISTORY_MAX", 10))

db: DatabaseManager = None
rag: RAGManager = None
executor: CodeExecutor = None
knowledge_db = None
learner: LearningEngine = None
researcher: DeepResearchAgent = None
reviewer: CodeReviewAgent = None
ingestor: DocumentIngestor = None
curator: MemoryCurator = None
profile: UserProfile = None
gpu_gate: GpuGate = None
coder_ws: "CoderWorkspace" = None
project_mem: ProjectMemory = None
lesson_mem: LessonMemory = None
VISION_MODEL = ""  # modelo de visão instalado (llava etc.) — resolvido no startup

# Cache em memória das sessões (lazy-loaded do banco)
sessions: dict[str, list] = defaultdict(list)
# Resumo rolante de conversas longas: {session_id: {"text": str, "upto": int}}
session_summaries: dict[str, dict] = {}
# Timestamp da última requisição do usuário (chat/agente) — usado pelo idle learning.
_last_request_at: float = 0.0


def _clean_topic(t: str) -> str:
    """Tira molduras do título para exibição no digest."""
    t = (t or "").strip()
    if t.startswith("Ideias centrais do livro "):
        t = "📖 " + t[len("Ideias centrais do livro "):]
    t = t.replace(" (enciclopédia)", "")
    return t[:90]


def _is_complex(question: str) -> bool:
    """Vale a pena usar o 14b nesta pergunta? Delegado a src/routing.py (testável)."""
    return is_complex(question)


def _installed_models() -> list[str]:
    """Lista os modelos do provedor ativo (Ollama ou motor próprio). [] em falha."""
    from src.providers import get_provider
    try:
        return get_provider().list_models()
    except Exception as e:
        logger.warning(f"Não consegui listar modelos do provedor: {e}")
        return []


def _pick_chat_model() -> str:
    """Escolhe um modelo leve para o chat (resposta rápida na CPU desta máquina).
    Prioridade: env CHAT_MODEL > melhor modelo leve instalado > modelo principal.
    Assim, se o usuário baixar um 3B depois, o chat acelera automaticamente."""
    if CHAT_MODEL:
        return CHAT_MODEL
    return pick_chat_model(_installed_models(), LIGHT_MODEL_PREFERENCE, MODEL)


def _pick_vision_model() -> str:
    """Acha um modelo de visão instalado (env VISION_MODEL tem prioridade)."""
    return pick_vision_model(_installed_models(), os.getenv("VISION_MODEL", "").strip())


def _init_knowledge():
    """Inicializa a base de conhecimento.

    Prioridade:
    1. Supabase (se SUPABASE_URL + SUPABASE_KEY estiverem configurados)
    2. LocalKnowledge (SQLite FTS5) — fallback automático, zero dependências externas.

    Ambos expõem a mesma interface — nenhum chamador precisa saber qual está ativo.
    """
    global knowledge_db
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if url and key:
        try:
            from src.knowledge import SupabaseKnowledge
            knowledge_db = SupabaseKnowledge(url=url, key=key)
            stats = knowledge_db.stats()
            logger.info(f"Supabase pronto — {stats['total']} artigos")
            return
        except Exception as e:
            logger.warning(f"Supabase indisponível: {e} — usando LocalKnowledge como fallback")
    # Fallback local: SQLite FTS5, sem dependências externas.
    local_path = os.getenv("LOCAL_KNOWLEDGE_PATH", "data/local_knowledge.db")
    from src.local_knowledge import LocalKnowledge
    knowledge_db = LocalKnowledge(path=local_path)
    logger.info(f"LocalKnowledge ativo (SQLite FTS5) em {local_path}")


async def _scheduler_loop():
    """Dispara estudos agendados e ativa aprendizado idle.

    Roda a cada 60s:
    - Se houver estudo agendado para agora, dispara.
    - Se o usuário estiver ocioso há mais de IDLE_TRIGGER segundos e o
      aprendizado estiver parado, inicia automaticamente (idle learning).
      O GpuGate já preempta o learner quando o usuário volta."""
    await asyncio.sleep(20)  # deixa o startup assentar
    while True:
        try:
            due = await asyncio.to_thread(db.due_schedules, datetime.now())
            for sch in due:
                logger.info(f"[scheduler] ⏰ Estudo agendado: {sch['topic'][:60]} ({sch['time_of_day']})")
                db.mark_schedule_ran(sch["id"], datetime.now())  # marca antes p/ não repetir
                if learner:
                    try:
                        res = await learner.study_now(sch["topic"])
                        ok = isinstance(res, dict) and res.get("ok")
                        msg = (f"📚 Estudei (agendado): {sch['topic'][:80]}" if ok
                               else f"⚠️ Estudo agendado '{sch['topic'][:60]}' não encontrou material")
                        db.add_notification(msg, kind="study",
                                            link=(res.get("url") if ok else "") or "")
                    except Exception as e:
                        logger.warning(f"[scheduler] erro ao estudar {sch['topic'][:40]}: {e}")
                        db.add_notification(f"❌ Falha no estudo agendado: {sch['topic'][:60]}", kind="study")

            # Idle learning: ativa o aprendizado autônomo quando a máquina está ociosa.
            if IDLE_TRIGGER > 0 and learner and not learner.running:
                idle = _time.perf_counter() - _last_request_at if _last_request_at > 0 else 0
                if idle > IDLE_TRIGGER:
                    logger.info(f"[idle] {idle:.0f}s sem requisição → iniciando aprendizado autônomo")
                    await learner.start()
        except Exception as e:
            logger.debug(f"[scheduler] loop: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, rag, executor, learner, researcher, reviewer, ingestor, curator, profile, gpu_gate, coder_ws, project_mem, lesson_mem, CHAT_MODEL, VISION_MODEL
    db = DatabaseManager(os.getenv("DATABASE_URL", "sqlite:///data/apolo.db"))
    rag = RAGManager(
        chroma_path=os.getenv("CHROMA_PATH", "./data/chroma_db"),
        examples_path=os.getenv("EXAMPLES_PATH", "./data/examples"),
        embed_model=os.getenv("EMBED_MODEL", "").strip() or None,
    )
    executor = CodeExecutor(timeout=int(os.getenv("EXECUTION_TIMEOUT", 30)))
    _init_knowledge()
    # A GPU é serializada pelo Ollama: o usuário tem prioridade sobre o aprendizado.
    gpu_gate = GpuGate()
    learner = LearningEngine(
        model=MODEL,
        rag=rag,
        knowledge_db=knowledge_db,
        db=db,
        interval_seconds=LEARNING_INTERVAL,
        summarize_model=SUMMARIZE_MODEL,
        gpu_gate=gpu_gate,
    )
    researcher = DeepResearchAgent(model=MODEL, rag=rag, knowledge_db=knowledge_db)
    reviewer = CodeReviewAgent(model=MODEL, rag=rag)
    ingestor = DocumentIngestor(rag=rag, knowledge_db=knowledge_db)
    curator = MemoryCurator(knowledge_db=knowledge_db, rag=rag, db=db)
    profile = UserProfile(path=os.getenv("PROFILE_PATH", "data/user_profile.json"))
    coder_ws = CoderWorkspace(root=os.getenv("APOLO_WORKSPACE", "./workspace"))
    project_mem = ProjectMemory(path=os.getenv("PROJECT_MEMORY_PATH", "data/project_contexts.json"))
    lesson_mem = LessonMemory(path=os.getenv("LESSONS_PATH", "data/lessons.db"))
    # Limpa títulos órfãos (sessões cujas mensagens já foram apagadas).
    try:
        orphans = db.cleanup_orphan_meta()
        if orphans:
            logger.info(f"Sessões fantasmas removidas: {orphans}")
    except Exception as e:
        logger.debug(f"cleanup_orphan_meta: {e}")
    # Resolve o modelo leve do chat (rápido na CPU); 14b fica para tarefas pesadas.
    CHAT_MODEL = _pick_chat_model()
    VISION_MODEL = _pick_vision_model()
    # Sumarização do aprendizado no modelo LEVE por padrão: com o 14b na CPU cada
    # síntese estourava o timeout de 120s (TODO item era salvo como conteúdo cru,
    # e a geração órfã seguia ocupando o Ollama, atrasando os próximos em cascata).
    # SUMMARIZE_MODEL definido no .env continua mandando.
    if not os.getenv("SUMMARIZE_MODEL", "").strip() and learner and CHAT_MODEL != MODEL:
        learner.summarize_model = CHAT_MODEL
        logger.info(f"[learner] sumarização no modelo leve: {CHAT_MODEL}")
    # Pré-carrega ambos os modelos — 1ª resposta sem cold start, mesmo quando AUTO_SMART
    # escala para 14b. O warmup do 14b roda 10s depois para não competir com o startup.
    asyncio.create_task(warmup(CHAT_MODEL))
    if MODEL != CHAT_MODEL:
        async def _delayed_warmup():
            await asyncio.sleep(10)
            await warmup(MODEL)
        asyncio.create_task(_delayed_warmup())
    # #6 Pre-warm ChromaDB — carrega o índice HNSW na RAM antes do usuário perguntar.
    # Sem isso, a 1ª busca semântica leva 200–400ms extras (load do índice do disco).
    async def _warmup_chroma():
        await asyncio.sleep(8)
        try:
            await asyncio.to_thread(rag.recall, "warmup apolo inicializacao", 1)
            logger.info("[chroma] índice HNSW pré-carregado")
        except Exception:
            pass
    asyncio.create_task(_warmup_chroma())

    # #7 Batch de notificações — enfileira escritas e persiste em batches de 2s.
    # Evita abrir uma sessão SQLAlchemy por notificação no learner.
    _notif_queue: list[dict] = []

    async def _notif_flush():
        while True:
            await asyncio.sleep(2)
            if _notif_queue:
                batch, _notif_queue[:] = _notif_queue[:], []
                for n in batch:
                    try:
                        db.add_notification(n["message"], kind=n.get("kind","info"),
                                            link=n.get("link",""))
                    except Exception:
                        pass

    # Expõe a função de enfileirar para uso no scheduler/learner
    app.state.queue_notification = lambda msg, kind="info", link="": \
        _notif_queue.append({"message": msg, "kind": kind, "link": link})
    asyncio.create_task(_notif_flush())

    # Agendador de estudos ("estude X toda manhã") — roda enquanto o servidor estiver no ar.
    scheduler_task = asyncio.create_task(_scheduler_loop(), name="scheduler")
    sm = f" — sumarização: {SUMMARIZE_MODEL}" if SUMMARIZE_MODEL != MODEL else ""
    cm = f" — chat: {CHAT_MODEL}" if CHAT_MODEL != MODEL else ""
    vm = f" — visão: {VISION_MODEL}" if VISION_MODEL else " — visão: (instale 'ollama pull llava')"
    logger.info(
        f"A.P.O.L.O. pronto — modelo: {MODEL}{cm}{sm}{vm} — keep_alive={KEEP_ALIVE} "
        f"— 7 agentes + auto-currículo + pesquisa profunda + code review + visão"
    )
    yield
    # Encerra learner e agendador ao desligar
    scheduler_task.cancel()
    if learner and learner.running:
        await learner.stop()


app = FastAPI(lifespan=lifespan)

# #3 Gzip: comprime respostas JSON >= 512 bytes (~3–5× menor em sessões longas)
app.add_middleware(GZipMiddleware, minimum_size=512)

# CORS — permite acesso de qualquer origem (necessário para acesso de celular/tablet na LAN).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


from src.telemetry import tracker as perf_tracker
import time as _time


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    """#8 Rate limiting — protege contra rajadas acidentais ou loops no browser.
    Janela deslizante de 60s por endpoint. Responde 429 se exceder o limite."""
    if RATE_LIMIT_ENABLED and request.url.path.startswith("/api/"):
        path = request.url.path
        limit = _RATE_LIMITS.get(path, _RATE_LIMITS["default"])
        now = _time.perf_counter()
        window = _rate_windows[path]
        _rate_windows[path] = [t for t in window if now - t < 60]
        if len(_rate_windows[path]) >= limit:
            return JSONResponse(
                {"error": "rate limit exceeded", "retry_after": 60},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        _rate_windows[path].append(now)
    return await call_next(request)


@app.middleware("http")
async def _token_auth_middleware(request: Request, call_next):
    """Autenticação por token para acesso remoto (API LAN).
    Se API_TOKEN não estiver definido, todas as requisições passam livremente.
    Quando definido, rotas /api/* que modificam estado (POST/DELETE/PATCH) exigem
    o header X-API-Token. GET endpoints continuam livres (só leitura)."""
    if API_TOKEN and request.url.path.startswith("/api/") and request.method not in ("GET", "OPTIONS"):
        if request.headers.get("X-API-Token", "") != API_TOKEN:
            return JSONResponse({"error": "unauthorized", "hint": "Header X-API-Token inválido"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def _latency_middleware(request: Request, call_next):
    """Mede a latência de cada requisição de API e registra na telemetria.
    Ignora assets estáticos para não poluir as métricas.

    Streaming (SSE) é registrado pelo tempo até a resposta começar — não dá para
    medir o fim sem consumir o corpo, então o valor é o *time-to-first-byte*."""
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    t0 = _time.perf_counter()
    is_error = False
    try:
        response = await call_next(request)
        is_error = response.status_code >= 500
        return response
    except Exception:
        is_error = True
        raise
    finally:
        ms = (_time.perf_counter() - t0) * 1000
        # Agrupa por rota "lógica" (sem query string).
        perf_tracker.record(path, ms, is_error=is_error)


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    use_web: bool = False
    smart: bool = False  # usa o modelo 14b (raciocínio mais profundo) em vez do leve
    image: str = ""      # imagem em base64 (sem prefixo data:) → roteia p/ modelo de visão


async def _gpu_priority(gen):
    """Enquanto a requisição do usuário streama, o learner cede a GPU a ela.
    O user_exit dispara mesmo se o cliente desconectar (o finally roda no close)."""
    if gpu_gate:
        gpu_gate.user_enter()
    try:
        async for ev in gen:
            yield ev
    finally:
        if gpu_gate:
            gpu_gate.user_exit()


def _get_session(session_id: str) -> list:
    """Retorna sessão do cache ou carrega do banco."""
    if session_id not in sessions:
        loaded = db.load_session(session_id)
        if loaded:
            sessions[session_id] = loaded
            logger.info(f"Sessão {session_id[:8]}... restaurada do banco ({len(loaded)} msgs)")
    return sessions[session_id]


# Pistas de que a mensagem fala do usuário — só aí vale a pena rodar a extração.
_FACT_CUES = (
    "meu ", "minha ", "eu ", " sou ", "estou ", "trabalho", "uso ", "utilizo",
    "prefiro", "gosto", "projeto", "stack", "nosso", "nossa", "to usando", "tô usando",
)


async def _maybe_extract_fact(message: str) -> None:
    """Aprende um fato pessoal a partir da mensagem (background, não bloqueia o chat).
    Só roda quando a mensagem tem cara de pessoal, p/ evitar ruído e custo de LLM."""
    if not profile:
        return
    low = message.lower()
    if not any(cue in low for cue in _FACT_CUES):
        return
    try:
        prompt = FACT_EXTRACT_PROMPT.format(message=message[:400])
        fact = await asyncio.to_thread(
            chat_resilient,
            CHAT_MODEL,
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE,
            options={"num_predict": 40},
        )
        fact = (fact or "").strip().strip('"').strip()
        if fact and "NONE" not in fact.upper() and len(fact) > 5:
            added = profile.add(fact, source="auto")
            if added:
                logger.info(f"[profile] fato auto-aprendido: {fact[:60]}")
    except Exception as e:
        logger.debug(f"fact extract: {e}")


async def _update_session_summary(session_id: str) -> None:
    """Resume as mensagens antigas de uma conversa longa (background, não bloqueia).
    A próxima resposta passa a contar com o resumo no system prompt."""
    hist = sessions.get(session_id, [])
    older = hist[:-MAX_HISTORY] if len(hist) > MAX_HISTORY else []
    if len(hist) <= SUMMARY_TRIGGER or not older:
        return
    convo = "\n".join(f"{m['role']}: {(m.get('content') or '')[:500]}" for m in older[-40:])
    try:
        prompt = CONVERSATION_SUMMARY_PROMPT.format(conversation=convo)
        text = await asyncio.to_thread(
            chat_resilient, CHAT_MODEL,
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE, options={"num_predict": 240},
        )
        text = (text or "").strip()
        if text:
            session_summaries[session_id] = {"text": text[:1500], "upto": len(older)}
            logger.info(f"[summary] sessão {session_id[:8]} resumida ({len(older)} msgs)")
            # Indexa a conversa no RAG para recall semântico em sessões futuras.
            if rag:
                title = db.list_sessions(0, 200)
                title = next((s.get("title", "") for s in title if s["session_id"] == session_id), "")
                all_msgs = sessions.get(session_id, [])
                await asyncio.to_thread(_index_episodic, session_id, title, all_msgs, rag, text)
    except Exception as e:
        logger.debug(f"summary: {e}")


async def _generate_session_title(session_id: str, first_message: str) -> None:
    """Gera título curto para a sessão usando LLM — roda em background."""
    try:
        prompt = SESSION_TITLE_PROMPT.format(message=first_message[:200])
        title = await asyncio.to_thread(
            chat_resilient,
            CHAT_MODEL,
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE,
        )
        title = (title or "").strip()[:80]
        if title:
            db.save_session_title(session_id, title)
    except Exception as e:
        logger.debug(f"Título de sessão: {e}")


@app.post("/api/chat")
async def chat(req: ChatRequest):
    global _last_request_at
    _last_request_at = _time.perf_counter()
    request = sanitize_request(req.message)
    history = _get_session(req.session_id)

    # Adiciona pergunta ao learner para estudo aprofundado
    if learner:
        learner.add_user_topic(request)

    # Auto-detecta necessidade de busca na web
    use_web = req.use_web
    if request.startswith("/web "):
        use_web = True
        request = request[5:].strip()

    async def stream():
        web_context = ""
        web_sources: list[dict] = []
        knowledge_context = ""

        # ── Fase 1: Busca na web ──────────────────────────────
        if use_web:
            yield f"data: {json.dumps({'type': 'status', 'message': 'Pesquisando na web...'})}\n\n"
            try:
                web_context, web_sources = await asyncio.wait_for(
                    web_research(request, max_results=2),
                    timeout=15.0,
                )
                if web_sources:
                    yield f"data: {json.dumps({'type': 'status', 'message': f'{len(web_sources)} fontes encontradas'})}\n\n"
                    if knowledge_db and web_context:
                        asyncio.create_task(asyncio.to_thread(
                            knowledge_db.save,
                            f"Pesquisa: {request[:100]}",
                            web_sources[0]["url"],
                            web_context,
                            "web_search",
                        ))
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'status', 'message': 'Busca expirou — continuando sem ela'})}\n\n"

        # ── Fast path: mensagens curtas (sim/não/ok/continue) ───────────────────
        # Não valem o custo de busca semântica — o modelo já tem o contexto no histórico.
        # Usa modelo leve sempre, sem recall, sem FTS, resposta quase instantânea.
        _is_short = len(request) <= SHORT_MSG_CHARS and not use_web and not bool(req.image)

        # ── Fase 2+3: memória semântica (ChromaDB) + base FTS (Supabase) EM PARALELO ──
        # Usar as duas fontes deixa a resposta mais embasada; rodar em paralelo não
        # custa latência (a busca demorada não soma com a outra).
        async def _do_recall() -> list[dict]:
            if not rag or _is_short:
                return []
            # #1 Cache: mesma query recente → resultado imediato, sem re-embedding
            recent = [m.get("content", "")[:80] for m in history[-4:]
                      if m.get("role") == "user"]
            topic_bias = " ".join(recent[:-1]).strip()
            enriched = (request + " " + topic_bias)[:450] if topic_bias else request
            cached = _qcache_recall_get(enriched)
            if cached is not None:
                return cached
            try:
                recalled = await asyncio.to_thread(rag.recall, enriched, MEMORY_RECALL_N)
                result = [
                    m for m in recalled if (m.get("relevance") or 0) >= MEMORY_MIN_RELEVANCE
                ][:MEMORY_TOP]
                return _qcache_recall_put(enriched, result)
            except Exception as e:
                logger.debug(f"recall: {e}")
                return []

        async def _do_fts() -> str:
            if not knowledge_db or _is_short:
                return ""
            # #2 Cache: FTS do mesmo query → resultado imediato
            cached = _qcache_fts_get(request)
            if cached is not None:
                return cached
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(knowledge_db.format_context, request),
                    timeout=KNOWLEDGE_TIMEOUT,
                )
                return _qcache_fts_put(request, result or "")
            except asyncio.TimeoutError:
                logger.debug("Knowledge FTS lenta — respondendo sem ela")
            except Exception as e:
                logger.warning(f"Knowledge FTS error: {e}")
            return ""

        memories, knowledge_context = await asyncio.gather(_do_recall(), _do_fts())

        # Lacuna de conhecimento: nenhuma memória semântica relevante.
        is_gap = not memories
        if is_gap and learner:
            learner.note_gap(request)
            try:
                db.add_notification(f"🔍 Lacuna detectada — vou estudar: {request[:80]}", kind="gap")
            except Exception:
                pass
            # Auto-pesquisa na web: em vez de responder no vácuo, busca informação
            # real antes de gerar a resposta. Desativa se o usuário já habilitou web
            # ou se há imagem (visão não precisa de web search).
            if AUTO_WEB_ON_GAP and not use_web and not bool(req.image):
                yield f"data: {json.dumps({'type': 'status', 'message': 'Sem memória sobre isso — pesquisando na web...'})}\n\n"
                try:
                    _gap_web, _gap_srcs = await asyncio.wait_for(
                        web_research(request, max_results=2),
                        timeout=12.0,
                    )
                    if _gap_srcs:
                        web_context = _gap_web
                        web_sources = _gap_srcs
                        is_gap = False  # agora tem contexto
                        yield f"data: {json.dumps({'type': 'status', 'message': f'{len(_gap_srcs)} fonte(s) encontrada(s) — integrando...'})}\n\n"
                        # Persiste o aprendizado em background
                        if knowledge_db and web_context:
                            asyncio.create_task(asyncio.to_thread(
                                knowledge_db.save,
                                f"Auto-pesquisa: {request[:100]}",
                                _gap_srcs[0]["url"],
                                web_context,
                                "web_search",
                            ))
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'status', 'message': 'Busca expirou — respondendo com o que sei...'})}\n\n"
                except Exception as _we:
                    logger.debug(f"auto-web on gap: {_we}")

        # Monta a seção de memória numerada (para o modelo citar [n]) + fontes p/ o front.
        memory_block = ""
        memory_sources: list[dict] = []
        if memories:
            blocks = []
            for i, m in enumerate(memories, 1):
                title = m.get("title") or "memória"
                snippet = (m.get("snippet") or "")[:MEMORY_SNIPPET]
                src = m.get("source") or ""
                blocks.append(f"[{i}] {title}\n{snippet}" + (f"\n(fonte: {src})" if src else ""))
                memory_sources.append({"n": i, "title": title, "url": src, "type": "knowledge"})
            memory_block = "\n\n".join(blocks)

        # ── Fase 4: Monta prompt ──────────────────────────────
        user_content = GENERATE_PROMPT.format(
            memory_section=MEMORY_SECTION.format(context=memory_block) if memory_block else "",
            knowledge_section=KNOWLEDGE_SECTION.format(context=knowledge_context) if knowledge_context else "",
            web_section=WEB_SECTION.format(context=web_context) if web_context else "",
            request=request,
        )

        # ── System prompt (com cache por sessão) ─────────────────
        # O conteúdo do system prompt muda apenas quando o perfil ou o projeto mudam —
        # não a cada mensagem. Cachear reduz recomputação e CPU usage.
        profile_facts = profile.as_context() if profile else ""
        proj_section  = project_mem.as_prompt_section() if project_mem else ""

        system_content = _syscache_get(req.session_id, profile_facts, proj_section)
        if system_content is None:
            system_content = SYSTEM_PROMPT
            if profile_facts:
                system_content += PERSONAL_SECTION.format(facts=profile_facts)
            if proj_section:
                system_content += proj_section
            _syscache_put(req.session_id, system_content, profile_facts, proj_section)

        # Memória de conversa longa: injeta o resumo das mensagens antigas (não enviadas).
        summ = session_summaries.get(req.session_id)
        if summ and len(history) > SUMMARY_TRIGGER and summ.get("text"):
            system_content += CONVERSATION_SUMMARY_SECTION.format(summary=summ["text"])

        messages = [{"role": "system", "content": system_content}]
        messages.extend(history[-MAX_HISTORY:])
        user_msg = {"role": "user", "content": user_content}

        # ── Visão: se há imagem, anexa-a e usa um modelo de visão local ──
        has_image = bool(req.image)
        if has_image and not VISION_MODEL:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Para eu analisar imagens, baixe um modelo de visão: ollama pull llava'})}\n\n"
            return
        if has_image:
            user_msg["images"] = [req.image]
        messages.append(user_msg)

        # Seleção de modelo: visão > inteligente (14b) > leve (chat do dia a dia).
        # Upgrade automático para 14b quando:
        #   (a) pergunta complexa (is_complex) — já existia
        #   (b) contexto rico (≥ MEMORY_RICH_14B memórias relevantes) — síntese profunda
        rich_context = len(memories) >= MEMORY_RICH_14B
        auto_smart = AUTO_SMART and not req.smart and not has_image and (
            _is_complex(request) or rich_context
        )
        smart = (req.smart or auto_smart) and MODEL != CHAT_MODEL
        if has_image:
            active_model, keep = VISION_MODEL, KEEP_ALIVE_HEAVY
            yield f"data: {json.dumps({'type': 'status', 'message': f'👁️ Analisando a imagem com {VISION_MODEL}...'})}\n\n"
        elif smart:
            active_model, keep = MODEL, KEEP_ALIVE_HEAVY
            if rich_context and not _is_complex(request):
                why = f"contexto rico ({len(memories)} memórias) — síntese profunda"
            else:
                why = "pergunta complexa detectada" if auto_smart else "modo inteligente"
            yield f"data: {json.dumps({'type': 'status', 'message': f'{why} — usando {MODEL}...'})}\n\n"
        else:
            active_model, keep = CHAT_MODEL, KEEP_ALIVE

        # ── Fase 5: Streaming do LLM (em thread — não bloqueia o event loop) ──
        full_response = ""
        try:
            async for token in stream_chat(active_model, messages, keep_alive=keep):
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # #6 Self-eval no chat: só quando usando 14b e resposta longa de texto.
            # Critica e refina — mesma lógica do agente, mas aplicada ao chat normal.
            if (CHAT_SELF_EVAL and smart and not has_image
                    and len(full_response) > 380 and "```" not in full_response[:200]):
                try:
                    verdict = await asyncio.to_thread(
                        chat_resilient, active_model,
                        [{"role": "user", "content":
                            AGENT_SELFEVAL_PROMPT.format(question=request, answer=full_response)}],
                        keep_alive=keep, options={"num_predict": 400},
                    )
                    verdict = (verdict or "").strip()
                    if verdict and verdict.upper() != "OK" and not verdict.upper().startswith("OK") \
                            and len(verdict) > 30:
                        # Envia o refinamento como tokens adicionais
                        delta = "\n\n---\n*Refinado:* " + verdict.lstrip()
                        for ch in delta:
                            full_response += ch
                            yield f"data: {json.dumps({'type': 'token', 'content': ch})}\n\n"
                except Exception as _se:
                    logger.debug(f"chat self-eval: {_se}")

            # Persiste mensagens no banco E no cache em memória
            is_first_message = len(sessions[req.session_id]) == 0
            sessions[req.session_id].append({"role": "user", "content": request})
            sessions[req.session_id].append({"role": "assistant", "content": full_response})
            db.save_message(req.session_id, "user", request)
            db.save_message(req.session_id, "assistant", full_response)

            # #10 Trim de sessão: evita crescimento ilimitado de RAM.
            # Mantém 2×MAX_HISTORY mensagens mais recentes — as antigas foram sumarizadas.
            _sess = sessions[req.session_id]
            _keep = 2 * MAX_HISTORY + 4
            if len(_sess) > _keep:
                sessions[req.session_id] = _sess[-_keep:]

            # Gera título da sessão na primeira mensagem (em background)
            if is_first_message:
                asyncio.create_task(_generate_session_title(req.session_id, request))

            # Aprende um fato pessoal sobre o usuário, se houver (background, não bloqueia)
            asyncio.create_task(_maybe_extract_fact(request))

            # Conversa longa: atualiza o resumo rolante (background) quando ficar defasado.
            hist_now = sessions[req.session_id]
            if len(hist_now) > SUMMARY_TRIGGER:
                s = session_summaries.get(req.session_id)
                if not s or (len(hist_now) - s.get("upto", 0)) > SUMMARY_STALE:
                    asyncio.create_task(_update_session_summary(req.session_id))

            code = extract_code(full_response)
            explanation = extract_explanation(full_response)
            has_code = "```" in full_response

            exec_result = None
            if has_code and code:
                exec_result = executor.run(code)
                if exec_result.success and rag:
                    rag.add_example(
                        content=f"# Pedido: {request}\n\n{code}",
                        doc_id=f"gerado_{hash(request) & 0xFFFFFF}",
                    )

            db.save_execution({
                "timestamp": datetime.now().isoformat(),
                "request": request,
                "result": code if has_code else full_response[:500],
                "status": "success" if (not exec_result or exec_result.success) else "error",
            })

            yield f"data: {json.dumps({'type': 'done', 'has_code': has_code, 'code': code, 'explanation': explanation, 'success': exec_result.success if exec_result else None, 'output': exec_result.stdout[:500] if exec_result else '', 'error': exec_result.stderr[:500] if exec_result else '', 'web_sources': web_sources, 'memory_sources': memory_sources, 'gap': is_gap, 'smart': smart, 'auto_smart': auto_smart, 'vision': has_image})}\n\n"

        except Exception as e:
            logger.error(f"Erro no stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/research")
async def research(req: ChatRequest):
    """Modo Pesquisa Profunda — raciocínio multi-etapas com memória + web, citado."""
    global _last_request_at
    _last_request_at = _time.perf_counter()
    question = sanitize_request(req.message)
    if learner:
        learner.add_user_topic(question)

    async def stream():
        answer, sources = "", []
        try:
            async for ev in researcher.research(question):
                if ev["type"] == "done":
                    answer = ev.get("answer", "")
                    sources = ev.get("sources", [])
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            logger.error(f"Erro na pesquisa: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Persiste a conversa (mesmo formato do chat) e salva na base de conhecimento
        if answer:
            is_first = len(sessions[req.session_id]) == 0
            sessions[req.session_id].append({"role": "user", "content": question})
            sessions[req.session_id].append({"role": "assistant", "content": answer})
            db.save_message(req.session_id, "user", question)
            db.save_message(req.session_id, "assistant", answer)
            if is_first:
                asyncio.create_task(_generate_session_title(req.session_id, question))
            if knowledge_db:
                asyncio.create_task(asyncio.to_thread(
                    knowledge_db.save,
                    f"Pesquisa profunda: {question[:120]}",
                    f"research://apolo/{abs(hash(question)) & 0xFFFFFFFF:08x}",
                    answer, "synthesis",
                ))

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReviewRequest(BaseModel):
    code: str
    language: str = "auto"


@app.post("/api/review")
async def review_code(req: ReviewRequest):
    """Code Review — revisa o código com apoio do conhecimento acumulado."""
    async def stream():
        try:
            async for ev in reviewer.review(req.code, req.language):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            logger.error(f"Erro no review: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _parse_coder_action(content: str) -> tuple[str, str, str]:
    """Decide a ação do A.P.O.L.O. Coder. Retorna (tipo, arg, payload).
    tipos: 'edit' | 'write' | 'read' | 'list' | 'run' | 'done'."""
    import re
    # EDITAR <arquivo> — edição cirúrgica com marcadores de conflito (preferível a
    # reescrever o arquivo inteiro). Formato:
    #   EDITAR caminho
    #   <<<<<<< (trecho exato existente) ======= (novo trecho) >>>>>>>
    m_edit = re.search(
        r"EDIT\w*\s+([^\n`]+?)\s*\n.*?<{3,}[^\n]*\n(.*?)\n={3,}[^\n]*\n(.*?)\n>{3,}",
        content, re.IGNORECASE | re.DOTALL)
    if m_edit:
        path = m_edit.group(1).strip().strip("`").strip('"').strip()
        return "edit", path, json.dumps({"old": m_edit.group(2), "new": m_edit.group(3)})
    for line in content.splitlines():
        # Tolera marcadores de lista/numeração que modelos leves adicionam ("1. ", "- ", "**").
        s = re.sub(r"^[\s\d\.\)\-\*\#`>]+", "", line).strip()
        # Verbos tolerantes a flexão/typo.
        m = re.match(r"(ESCREV\w*|LIST\w*|ROD\w*|BUSC\w*|ACH\w*|PROCUR\w*|APAG\w*|REMOV\w*|SUBSTITU\w*|MOV\w*|RENOME\w*|LER|LEIA)\s+(.+)", s, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).upper()
        verb = ("ESCREVER" if raw.startswith("ESCREV") else
                "LISTAR" if raw.startswith("LIST") else
                "RODAR" if raw.startswith("ROD") else
                "BUSCAR" if raw.startswith("BUSC") or raw.startswith("PROCUR") else
                "ACHAR" if raw.startswith("ACH") else
                "APAGAR" if raw.startswith("APAG") or raw.startswith("REMOV") else
                "SUBSTITUIR" if raw.startswith("SUBSTITU") else
                "MOVER" if raw.startswith("MOV") or raw.startswith("RENOME") else "LER")
        arg = m.group(2).strip().strip("`").strip()
        if verb == "ESCREVER":
            body = extract_fenced(content)
            if body is not None:
                return "write", arg, body
            # sem bloco ainda — trata como pedido incompleto; deixa o modelo refazer
            return "write", arg, ""
        if verb == "LER":
            # LER caminho:10-80 — leitura parcial por faixa de linhas (arquivos grandes)
            m_rng = re.match(r"(.+?):(\d+)-(\d+)$", arg)
            if m_rng:
                return "read", m_rng.group(1).strip(), f"{m_rng.group(2)}-{m_rng.group(3)}"
            return "read", arg, ""
        if verb == "LISTAR":
            return "list", arg, ""
        if verb == "RODAR":
            return "run", arg, ""
        if verb == "BUSCAR":
            return "search", arg, ""
        if verb == "ACHAR":
            return "find", arg, ""
        if verb == "APAGAR":
            return "delete", arg, ""
        if verb == "SUBSTITUIR":
            # formato: <texto> ==> <novo>
            if "==>" in arg:
                find, rep = arg.split("==>", 1)
                return "replace", find.strip().strip('"'), rep.strip().strip('"')
            return "done", "", content  # malformado → ignora
        if verb == "MOVER":
            if "==>" in arg:
                src, dst = arg.split("==>", 1)
                return "move", src.strip().strip('"'), dst.strip().strip('"')
            parts = arg.split()
            if len(parts) == 2:
                return "move", parts[0], parts[1]
            return "done", "", content
    return "done", "", content


@app.post("/api/coder")
async def coder(req: ChatRequest):
    """A.P.O.L.O. Coder — o "Claude Code" interno: lê/escreve arquivos e roda
    comandos num workspace isolado, em loop ReAct, até concluir a tarefa."""
    task = sanitize_request(req.message)
    # smart=True usa o 14b (raciocínio mais profundo p/ tarefas difíceis); senão o leve.
    model = MODEL if req.smart else CHAT_MODEL
    keep = KEEP_ALIVE_HEAVY if req.smart else KEEP_ALIVE

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        answer = ""
        t0 = _time.time()
        try:
            system_content = CODER_SYSTEM + CODER_DOCTRINE + CODER_TREE_SECTION.format(tree=coder_ws.tree())
            # Memória de Projeto: se há um projeto memorizado (🎯), o Coder conhece
            # a stack/dependências desde o 1º passo — mesmo contexto que o chat usa.
            if project_mem:
                _proj_sec = project_mem.as_prompt_section()
                if _proj_sec:
                    system_content += _proj_sec
            # ── Autoaprendizado: injeta lições de tarefas anteriores parecidas ──
            # O Coder lê a própria experiência (regressões revertidas, reflexões)
            # antes de agir — mesmo mecanismo de memória do Claude Code.
            if lesson_mem:
                lessons_block = await asyncio.to_thread(lesson_mem.format_section, task)
                if lessons_block:
                    system_content += lessons_block
                    n_les = lessons_block.count("\n- ")
                    yield _ev({"type": "step", "icon": "🧠",
                               "message": f"Aplicando {n_les} lição(ões) aprendida(s) em tarefas anteriores"})
            mlabel = "14b (inteligente)" if req.smart else "leve (rápido)"
            yield _ev({"type": "step", "icon": "💻", "message": f"Planejando a tarefa... [modelo {mlabel}]"})

            # ── Fase de planejamento: o modelo descreve seu plano ANTES de agir ──
            # Isso força o modelo a entender a tarefa por inteiro antes de tocar
            # qualquer arquivo — reduz saltos precipitados e mudanças erradas.
            plan_text = ""
            try:
                plan_prompt = CODER_PLAN_PROMPT.format(task=task)
                plan_raw = await asyncio.to_thread(
                    chat_resilient, model,
                    [{"role": "system", "content": system_content},
                     {"role": "user", "content": plan_prompt}],
                    keep_alive=keep,
                ) or ""
                plan_text = plan_raw.strip()
            except Exception as _pe:
                logger.debug(f"plan: {_pe}")
            if plan_text:
                yield _ev({"type": "plan", "text": plan_text})

            # Monta o histórico com o plano já comprometido (o modelo sabe o que prometeu).
            messages = [{"role": "system", "content": system_content},
                        {"role": "user", "content": f"Tarefa: {task}"}]
            if plan_text:
                messages.append({"role": "assistant", "content": f"Plano:\n{plan_text}"})
                messages.append({"role": "user", "content":
                    "Bom. Execute o PRIMEIRO passo do plano. Apenas UMA ação (sem lista, sem explicação):"})
            yield _ev({"type": "step", "icon": "🚀", "message": "Iniciando execução..."})

            # Guarda de regressão: se o workspace tem suíte de testes, captura o estado
            # base (verde/vermelho). Ao final, se as alterações deixarem a suíte vermelha
            # (e ela estava verde), desfaz tudo automaticamente. Protege o projeto de uma
            # automelhoria destrutiva. Sem suíte (ex.: ./workspace isolado) → sem custo.
            _root = str(coder_ws.root)
            has_tests = os.path.isdir(os.path.join(_root, "tests")) or \
                os.path.exists(os.path.join(_root, "pytest.ini"))
            baseline_green = False
            if has_tests:
                _cached = _coder_baseline_cache.get(_root)
                if _cached and (_time.time() - _cached[1]) < CODER_BASELINE_TTL:
                    baseline_green = _cached[0]
                    yield _ev({"type": "step", "icon": "🛡️",
                               "message": f"Baseline em cache ({int(_time.time() - _cached[1])}s atrás): "
                                          f"testes {'PASSANDO' if baseline_green else 'vermelhos (guarda desativada)'} — suíte não re-rodada"})
                else:
                    yield _ev({"type": "step", "icon": "🛡️", "message": "Guarda de regressão: verificando a suíte de testes (baseline)..."})
                    baseline_green, _ = await asyncio.to_thread(coder_ws.run_cmd, "python -m pytest -q", 300)
                    _coder_baseline_cache[_root] = (baseline_green, _time.time())
                    yield _ev({"type": "step", "icon": "🛡️",
                               "message": f"Baseline: testes {'PASSANDO' if baseline_green else 'já vermelhos (guarda desativada)'}"})

            wrote_files = False
            did_run = False
            nudged = False
            reverted = False
            rescue_used = False          # resgate único p/ resposta sem ação válida
            last_sig: tuple = ("", "")   # anti-loop: última (ação, alvo) executada
            repeat_count = 0
            steps_used = 0
            actions_log: list[str] = []  # trilha p/ reflexão pós-tarefa
            compact_notified = False

            async def _syntax_check(path: str) -> str:
                """Verificação sintática automática pós-escrita (custo ~0, sem LLM):
                erro de sintaxe é detectado NA HORA, não no RODAR três passos depois."""
                if not path.endswith(".py"):
                    return ""
                ok_c, out_c = await asyncio.to_thread(
                    coder_ws.run_cmd, f'python -m py_compile "{path}"', 30)
                if ok_c:
                    return ""
                return (f"\n⚠️ VERIFICAÇÃO AUTOMÁTICA: py_compile FALHOU neste arquivo:\n"
                        f"{out_c[:500]}\nConserte a sintaxe ANTES de qualquer outra ação.")

            for step in range(MAX_CODER_STEPS):
                if gpu_gate and req.smart:
                    await gpu_gate.wait_for_idle()
                # Compactação de contexto: histórico longo → observações antigas
                # encolhem; tarefa/plano (head) e o presente (tail) ficam intactos.
                compacted = compact_messages(messages, CODER_CTX_CHARS)
                if compacted is not messages:
                    messages = compacted
                    if not compact_notified:
                        compact_notified = True
                        yield _ev({"type": "step", "icon": "🗜️",
                                   "message": "Contexto compactado — observações antigas resumidas para não estourar a janela"})
                content = await asyncio.to_thread(
                    chat_resilient, model, messages, keep_alive=keep,
                ) or ""
                action, arg, payload = _parse_coder_action(content)
                steps_used = step + 1

                if action == "done":
                    # Resgate único: o modelo despejou código solto (bloco ``` sem
                    # ESCREVER/EDITAR) ou veio vazio — sem isto, a tarefa terminaria
                    # "concluída" sem o código ter ido para arquivo nenhum.
                    stray_code = "```" in content and "CONCLU" not in content.upper()
                    if (stray_code or not content.strip()) and not rescue_used:
                        rescue_used = True
                        yield _ev({"type": "step", "icon": "🩹",
                                   "message": "Resposta sem ação válida — pedindo o formato correto..."})
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content":
                            "Sua resposta NÃO continha uma ação válida. Escolha UMA ação no formato exato: "
                            "para criar/alterar arquivo, 'ESCREVER <caminho>' (ou 'EDITAR <caminho>') "
                            "seguido do conteúdo; para terminar, 'CONCLUIR' + resumo. Refaça agora:"})
                        continue
                    # Não deixa concluir sem verificar: se escreveu código mas nunca rodou,
                    # exige uma execução real (evita "achar" que funciona sem testar).
                    if wrote_files and not did_run and not nudged:
                        nudged = True
                        yield _ev({"type": "step", "icon": "🧪", "message": "Escreveu código mas não testou — exigindo verificação..."})
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content":
                            "Você ainda NÃO verificou. Antes de concluir, RODE um comando para testar "
                            "de verdade (ex.: 'pytest -q' ou 'python <arquivo>'). Escreva só a ação RODAR."})
                        continue
                    answer = content
                    break

                messages.append({"role": "assistant", "content": content})

                if action == "list":
                    out = await asyncio.to_thread(coder_ws.list_dir, arg or ".")
                    yield _ev({"type": "step", "icon": "📂", "message": f"LISTAR {arg or '.'}"})
                    obs = f"Conteúdo de '{arg or '.'}':\n{out}"
                elif action == "read":
                    if payload:  # faixa de linhas "início-fim"
                        _a, _b = payload.split("-", 1)
                        out = await asyncio.to_thread(
                            coder_ws.read_file, arg, 6000, int(_a), int(_b))
                        yield _ev({"type": "step", "icon": "📖", "message": f"LER {arg}:{payload}"})
                    else:
                        out = await asyncio.to_thread(coder_ws.read_file, arg)
                        yield _ev({"type": "step", "icon": "📖", "message": f"LER {arg}"})
                    obs = f"Arquivo '{arg}':\n```\n{out}\n```"
                elif action == "search":
                    out = await asyncio.to_thread(coder_ws.search, arg)
                    yield _ev({"type": "step", "icon": "🔎", "message": f"BUSCAR {arg[:60]}"})
                    obs = f"Resultados de busca por '{arg}':\n{out}\n\nUse para se localizar. Próxima ação."
                elif action == "find":
                    out = await asyncio.to_thread(coder_ws.find_files, arg)
                    yield _ev({"type": "step", "icon": "🗂️", "message": f"ACHAR {arg[:60]}"})
                    obs = f"Arquivos que combinam com '{arg}':\n{out}\n\nPróxima ação."
                elif action == "delete":
                    out = await asyncio.to_thread(coder_ws.delete_file, arg)
                    yield _ev({"type": "step", "icon": "🗑️", "message": f"APAGAR {arg}"})
                    obs = f"{out}\n\nPróxima ação ou CONCLUIR."
                elif action == "move":
                    out = await asyncio.to_thread(coder_ws.rename_file, arg, payload)
                    yield _ev({"type": "step", "icon": "📦", "message": f"MOVER {arg} → {payload}"})
                    obs = f"{out}\n\nPróxima ação ou CONCLUIR."
                elif action == "replace":
                    res = await asyncio.to_thread(coder_ws.search_replace, arg, payload)
                    n_files = res.get("files_changed", 0)
                    yield _ev({"type": "step", "icon": "🔁",
                               "message": f"SUBSTITUIR '{arg[:30]}' → '{payload[:30]}' ({n_files} arquivo(s), {res.get('count',0)} ocorr.)"})
                    obs = f"Substituição: {json.dumps(res.get('files', []), ensure_ascii=False)[:600]}\n\nVerifique (RODAR) e CONCLUIR."
                elif action == "edit":
                    spec = json.loads(payload)
                    old_content = await asyncio.to_thread(coder_ws.current_content, arg)
                    out = await asyncio.to_thread(coder_ws.edit_file, arg, spec.get("old", ""), spec.get("new", ""))
                    if out.startswith("OK"):
                        wrote_files = True
                        new_content = await asyncio.to_thread(coder_ws.current_content, arg)
                        diff = make_diff(old_content, new_content, arg)
                        yield _ev({"type": "step", "icon": "✏️",
                                   "message": f"EDITAR {arg} (+{diff['added']} -{diff['removed']})"})
                        if diff["text"]:
                            yield _ev({"type": "diff", "path": arg, "diff": diff["text"]})
                        _related = await asyncio.to_thread(coder_ws.find_related_tests, arg)
                        if _related:
                            yield _ev({"type": "test_hint", "path": arg, "tests": _related})
                    else:
                        yield _ev({"type": "step", "icon": "✗", "message": f"EDITAR {arg} — {out[:80]}"})
                    chk = await _syntax_check(arg) if out.startswith("OK") else ""
                    if chk:
                        yield _ev({"type": "step", "icon": "🧪",
                                   "message": f"py_compile falhou em {arg} — devolvendo o erro ao modelo"})
                    actions_log.append(
                        f"EDITAR {arg} → {'ok' if out.startswith('OK') else 'FALHOU: ' + out[:100]}"
                        + (" (sintaxe quebrada detectada)" if chk else ""))
                    obs = out + chk + "\n\nPróxima ação (verifique com RODAR antes de CONCLUIR)."
                elif action == "write":
                    if not payload:
                        obs = "Faltou o bloco ``` com o conteúdo do arquivo. Reenvie ESCREVER + bloco."
                        yield _ev({"type": "step", "icon": "✗", "message": f"ESCREVER {arg} — sem conteúdo"})
                    else:
                        old = await asyncio.to_thread(coder_ws.current_content, arg)
                        diff = make_diff(old, payload, arg)
                        out = await asyncio.to_thread(coder_ws.write_file, arg, payload)
                        wrote_files = True
                        verb = "criou" if diff["is_new"] else "alterou"
                        yield _ev({"type": "step", "icon": "✍️",
                                   "message": f"ESCREVER {arg} — {verb} (+{diff['added']} -{diff['removed']})"})
                        if diff["text"]:
                            yield _ev({"type": "diff", "path": arg, "diff": diff["text"]})
                        # Testes inteligentes: detecta arquivos de teste relacionados ao arquivo escrito.
                        _related = await asyncio.to_thread(coder_ws.find_related_tests, arg)
                        if _related:
                            yield _ev({"type": "test_hint", "path": arg, "tests": _related})
                        chk = await _syntax_check(arg)
                        if chk:
                            yield _ev({"type": "step", "icon": "🧪",
                                       "message": f"py_compile falhou em {arg} — devolvendo o erro ao modelo"})
                        actions_log.append(
                            f"ESCREVER {arg} (+{diff['added']} -{diff['removed']})"
                            + (" (sintaxe quebrada detectada)" if chk else ""))
                        obs = out + chk
                elif action == "run":
                    did_run = True
                    yield _ev({"type": "step", "icon": "⚙️", "message": f"RODAR {arg[:70]}"})
                    # Executa transmitindo a saída ao vivo (linha a linha) via uma fila.
                    q: asyncio.Queue = asyncio.Queue()
                    loop = asyncio.get_event_loop()
                    out_lines: list[str] = []

                    def _worker():
                        ok_local = False
                        for kind, val in coder_ws.run_cmd_stream(arg):
                            if kind == "line":
                                loop.call_soon_threadsafe(q.put_nowait, ("line", val))
                            else:
                                ok_local = val
                        loop.call_soon_threadsafe(q.put_nowait, ("done", ok_local))

                    fut = loop.run_in_executor(None, _worker)
                    ok = False
                    while True:
                        kind, val = await q.get()
                        if kind == "line":
                            out_lines.append(val)
                            yield _ev({"type": "cmd_line", "content": val[:300]})
                        else:
                            ok = val
                            break
                    await fut
                    out = "\n".join(out_lines).strip() or "(sem saída)"
                    actions_log.append(
                        f"RODAR {arg[:60]} → " + ("ok" if ok else f"FALHOU: {out[-160:].strip()}"))
                    yield _ev({"type": "step", "icon": "✓" if ok else "✗",
                               "message": f"{'ok' if ok else 'falhou'}: {out[:120].strip()}"})
                    obs = f"Resultado de '{arg}' ({'sucesso' if ok else 'erro'}):\n```\n{out[:2000]}\n```"
                else:
                    obs = ""

                # Anti-loop: repetir a MESMA ação com o MESMO alvo é sinal de que o
                # modelo travou (o resultado não vai mudar). 1ª repetição → aviso
                # explícito; 2ª → encerra o loop e pede a conclusão com o que há.
                if (action, arg) == last_sig:
                    repeat_count += 1
                else:
                    repeat_count = 0
                    last_sig = (action, arg)
                if repeat_count >= 2:
                    yield _ev({"type": "step", "icon": "🔁",
                               "message": f"Loop detectado ({action.upper()} {arg[:40]} repetido 3×) — encerrando para não desperdiçar passos."})
                    messages.append({"role": "user", "content":
                        obs + "\n\nVocê repetiu a mesma ação 3 vezes — PARE. CONCLUA agora resumindo o que conseguiu e o que ficou pendente."})
                    break
                if repeat_count == 1:
                    obs = ("⚠️ Você REPETIU exatamente a ação anterior — o resultado é o mesmo. "
                           "NÃO repita de novo; tente uma abordagem DIFERENTE.\n\n" + obs)

                messages.append({"role": "user", "content":
                    obs + "\n\nPróxima ação (ou CONCLUIR com o resumo final)."})

            if not answer:
                messages.append({"role": "user", "content":
                    "Pare e CONCLUA: resuma em português o que você fez no workspace, sem mais ações."})
                answer = await asyncio.to_thread(chat_resilient, model, messages, keep_alive=keep) or "Tarefa encerrada."

            import re as _re
            answer = _re.sub(r"^[\s*#>`-]*CONCLUIR\s*:?\s*", "", answer, flags=_re.IGNORECASE).strip()

            # Guarda de regressão (a rede de proteção): se escreveu arquivos e a suíte
            # estava verde no início, ela PRECISA continuar verde. Senão, desfaz tudo.
            if wrote_files and has_tests and baseline_green:
                yield _ev({"type": "step", "icon": "🛡️", "message": "Guarda de regressão: revalidando a suíte após as alterações..."})
                final_green, final_out = await asyncio.to_thread(coder_ws.run_cmd, "python -m pytest -q", 300)
                if final_green:
                    _coder_baseline_cache[_root] = (True, _time.time())
                else:
                    # Revert restaura os arquivos, mas re-mede na próxima tarefa.
                    _coder_baseline_cache.pop(_root, None)
                if not final_green:
                    reverted = True
                    res = await asyncio.to_thread(coder_ws.undo_all)
                    n = res.get("reverted", 0) if isinstance(res, dict) else res
                    yield _ev({"type": "step", "icon": "↩️",
                               "message": f"Testes FICARAM VERMELHOS — revertendo {n} alteração(ões) para proteger o projeto."})
                    tail = "\n".join(final_out.strip().splitlines()[-12:])
                    # ── Autoaprendizado com a falha ──
                    # 1) Lição permanente: da próxima vez que pegar tarefa parecida,
                    #    o Coder verá este aviso ANTES de repetir o erro.
                    if lesson_mem:
                        await asyncio.to_thread(
                            lesson_mem.add, task,
                            f"Em tarefa parecida, minhas mudanças quebraram a suíte e foram "
                            f"revertidas (erro: {tail[-180:].strip()}). Rodar os testes relacionados "
                            f"ANTES de concluir e preferir EDITAR cirúrgico a reescrever.",
                            "regression")
                        yield _ev({"type": "step", "icon": "🧠",
                                   "message": "Lição de regressão registrada — não vou repetir esse erro."})
                    # 2) Loop fechado Coder → Learner: o tema da falha vira estudo
                    #    prioritário do autoaprendizado (fecha o ciclo de autonomia).
                    if learner:
                        learner.note_gap(task)
                        learner.add_user_topic(task)
                        yield _ev({"type": "step", "icon": "📚",
                                   "message": "Tema enviado ao autoaprendizado — vou estudar o assunto antes da próxima tentativa."})
                    answer = ("⚠️ **Alterações revertidas automaticamente pela guarda de regressão.**\n\n"
                              "A suíte de testes estava passando antes, mas ficou vermelha depois das "
                              "mudanças — então elas foram desfeitas e o projeto está intacto. "
                              "Isso normalmente indica que o modelo quebrou algo (ex.: reescreveu um "
                              "módulo errado). Tente de novo com o modelo 🧠 14b e uma tarefa mais específica.\n\n"
                              f"Saída final dos testes:\n```\n{tail}\n```")
                else:
                    yield _ev({"type": "step", "icon": "✅", "message": "Guarda de regressão: suíte continua verde — alterações preservadas."})

            # ── Reflexão pós-tarefa (autoaprendizado): extrai UMA lição da execução ──
            # Usa o modelo LEVE (1 chamada curta) e guarda em data/lessons.db; a lição
            # é injetada automaticamente nas próximas tarefas parecidas.
            if CODER_REFLECT and lesson_mem and wrote_files and not reverted and actions_log:
                try:
                    outcome = "\n".join(actions_log[-15:])[:2500]
                    refl = (await asyncio.to_thread(
                        chat_resilient, CHAT_MODEL,
                        [{"role": "user", "content":
                          CODER_REFLECT_PROMPT.format(task=task[:300], outcome=outcome)}],
                        keep_alive=KEEP_ALIVE) or "").strip()
                    if refl and not refl.upper().startswith("NONE") and len(refl) >= 15:
                        saved = await asyncio.to_thread(
                            lesson_mem.add, task, refl[:600], "reflection")
                        if saved:
                            yield _ev({"type": "step", "icon": "🧠",
                                       "message": f"Lição aprendida: {refl[:120]}"})
                except Exception as _refl_err:
                    logger.debug(f"coder reflect: {_refl_err}")

            # Diário de bordo: cada tarefa vira um registro persistente (passos,
            # duração, escreveu/rodou/revertida) — autonomia visível + matéria-prima
            # para acompanhar a taxa de sucesso do Coder ao longo do tempo.
            if db:
                try:
                    await asyncio.to_thread(
                        db.save_coder_task, task, model, steps_used, wrote_files,
                        did_run, reverted, _time.time() - t0, answer)
                except Exception as _journal_err:
                    logger.debug(f"coder journal: {_journal_err}")

            yield _ev({"type": "step", "icon": "📁", "message": f"Workspace:\n{coder_ws.tree(40)}"})
            yield _ev({"type": "token", "content": answer})
            yield _ev({"type": "done", "answer": answer})
        except Exception as e:
            logger.error(f"Erro no coder: {e}", exc_info=True)
            yield _ev({"type": "error", "message": str(e)})

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/coder/files")
async def coder_files():
    """Árvore, lista plana e raiz do workspace do Coder (para o painel)."""
    return {"root": str(coder_ws.root), "tree": coder_ws.tree(80),
            "files": coder_ws.list_files(200), "changes": coder_ws.list_changes()}


@app.get("/api/coder/lessons")
async def coder_lessons():
    """Memória de lições do Coder — o que ele aprendeu com as próprias tarefas."""
    if not lesson_mem:
        return {"count": 0, "lessons": []}
    return {"count": lesson_mem.count(), "lessons": lesson_mem.recent(30)}


@app.delete("/api/coder/lessons/{lesson_id}")
async def coder_lesson_delete(lesson_id: int):
    """Curadoria: remove uma lição errada/obsoleta da memória do Coder."""
    ok = lesson_mem.delete(lesson_id) if lesson_mem else False
    return {"ok": ok}


@app.get("/api/coder/tasks")
async def coder_tasks(limit: int = 20):
    """Diário de bordo do Coder — tarefas executadas + taxa de sucesso."""
    if not db:
        return {"stats": {"total": 0}, "tasks": []}
    stats, tasks = await asyncio.gather(
        asyncio.to_thread(db.get_coder_stats),
        asyncio.to_thread(db.get_coder_tasks, limit),
    )
    return {"stats": stats, "tasks": tasks}


class CoderExecRequest(BaseModel):
    cmd: str


@app.websocket("/ws/coder/exec")
async def coder_exec_ws(ws: WebSocket):
    """#9 WebSocket para o terminal do Coder — bidirecional real.
    Recebe {cmd} → transmite linhas de saída → envia {type: done, ok: bool}.
    Vantagem sobre SSE: permite enviar Ctrl+C para interromper processos."""
    await ws.accept()
    try:
        data = await ws.receive_json()
        cmd = (data.get("cmd") or "").strip()
        if not cmd:
            await ws.send_json({"type": "done", "ok": False, "error": "cmd vazio"})
            return

        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _worker():
            for kind, val in coder_ws.run_cmd_stream(cmd):
                loop.call_soon_threadsafe(q.put_nowait, (kind, val))

        fut = loop.run_in_executor(None, _worker)
        ok = False
        while True:
            kind, val = await q.get()
            if kind == "line":
                await ws.send_json({"type": "line", "content": val[:500]})
            else:
                ok = val
                break
        await fut
        _invalidate_baseline()  # o comando pode ter mudado o workspace
        await ws.send_json({"type": "done", "ok": ok})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"type": "error", "message": str(e)[:200]})
        except Exception:
            pass


@app.post("/api/coder/exec")
async def coder_exec(req: CoderExecRequest):
    """Executa um comando direto no workspace (sem o loop LLM), transmitindo a saída
    ao vivo — um terminal leve confinado ao workspace, com as mesmas proteções."""
    cmd = (req.cmd or "").strip()

    def _ev(d): return f"data: {json.dumps(d)}\n\n"

    async def stream():
        if not cmd:
            yield _ev({"type": "done", "ok": False}); return
        yield _ev({"type": "step", "icon": "⚙️", "message": f"$ {cmd[:80]}"})
        q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def _worker():
            ok_local = False
            for kind, val in coder_ws.run_cmd_stream(cmd):
                if kind == "line":
                    loop.call_soon_threadsafe(q.put_nowait, ("line", val))
                else:
                    ok_local = val
            loop.call_soon_threadsafe(q.put_nowait, ("done", ok_local))

        fut = loop.run_in_executor(None, _worker)
        ok = False
        while True:
            kind, val = await q.get()
            if kind == "line":
                yield _ev({"type": "cmd_line", "content": val[:300]})
            else:
                ok = val; break
        await fut
        _invalidate_baseline()  # o comando pode ter mudado o workspace
        yield _ev({"type": "step", "icon": "✓" if ok else "✗", "message": "concluído" if ok else "falhou"})
        yield _ev({"type": "done", "ok": ok})

    return StreamingResponse(_gpu_priority(stream()), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/coder/read")
async def coder_read(path: str):
    """Conteúdo de um arquivo do workspace (para o visualizador do painel)."""
    content = await asyncio.to_thread(coder_ws.read_file, path, 20000)
    return {"path": path, "content": content}


class CoderPathRequest(BaseModel):
    path: str


@app.post("/api/coder/delete")
async def coder_delete(req: CoderPathRequest):
    """Apaga um arquivo do workspace (reversível via histórico)."""
    out = await asyncio.to_thread(coder_ws.delete_file, req.path)
    _invalidate_baseline()
    return {"ok": out.startswith("OK"), "message": out}


class CoderReplaceRequest(BaseModel):
    find: str
    replace: str = ""


@app.post("/api/coder/replace")
async def coder_replace(req: CoderReplaceRequest):
    """Busca-e-substitui em massa no workspace (cada arquivo vira snapshot reversível)."""
    res = await asyncio.to_thread(coder_ws.search_replace, req.find, req.replace)
    _invalidate_baseline()
    return res


@app.get("/api/coder/git")
async def coder_git():
    """Status do git no workspace (se for um repositório)."""
    return await asyncio.to_thread(coder_ws.git_status)


class CoderCommitRequest(BaseModel):
    message: str = ""


@app.post("/api/coder/commit")
async def coder_commit(req: CoderCommitRequest):
    """Commit assistido: sem mensagem, o modelo leve gera uma (Conventional
    Commits) a partir do diff real. NUNCA faz push (bloqueado no sandbox)."""
    msg = (req.message or "").strip()
    if not msg:
        st = await asyncio.to_thread(coder_ws.git_status)
        if not st.get("is_repo"):
            return {"ok": False, "error": "o workspace não é um repositório git"}
        if not st.get("dirty"):
            return {"ok": False, "error": "nada para commitar"}
        diff = await asyncio.to_thread(coder_ws.git_diff)
        prompt = COMMIT_MSG_PROMPT.format(
            status=(st.get("status") or "")[:800], diff=diff[:3000])
        try:
            raw = await asyncio.to_thread(
                chat_resilient, CHAT_MODEL,
                [{"role": "user", "content": prompt}], keep_alive=KEEP_ALIVE) or ""
            msg = raw.strip().splitlines()[0].strip().strip('`"\'')[:150]
        except Exception as e:
            logger.debug(f"commit msg: {e}")
        if not msg:
            msg = "chore: alterações via A.P.O.L.O. Coder"
    return await asyncio.to_thread(coder_ws.git_commit_all, msg)


@app.get("/api/coder/git/diff")
async def coder_git_diff(path: str = ""):
    """Diff do git (todo o workspace ou um arquivo)."""
    diff = await asyncio.to_thread(coder_ws.git_diff, path)
    return {"path": path, "diff": diff}


class CoderMoveRequest(BaseModel):
    src: str
    dst: str


@app.post("/api/coder/move")
async def coder_move(req: CoderMoveRequest):
    """Renomeia/move um arquivo no workspace (reversível)."""
    out = await asyncio.to_thread(coder_ws.rename_file, req.src, req.dst)
    _invalidate_baseline()
    return {"ok": out.startswith("OK"), "message": out}


class CoderUndoRequest(BaseModel):
    path: str = ""
    all: bool = False


@app.post("/api/coder/undo")
async def coder_undo(req: CoderUndoRequest):
    """Desfaz/descarta alterações feitas pelo Coder (snapshots da sessão)."""
    _invalidate_baseline()
    if req.all:
        return await asyncio.to_thread(coder_ws.undo_all)
    if req.path:
        return await asyncio.to_thread(coder_ws.undo_file, req.path)
    return await asyncio.to_thread(coder_ws.undo_last)


class CoderWorkspaceRequest(BaseModel):
    path: str


@app.post("/api/coder/workspace")
async def coder_set_workspace(req: CoderWorkspaceRequest):
    """Aponta o Coder para um diretório existente (projeto real)."""
    res = await asyncio.to_thread(coder_ws.set_root, req.path)
    _invalidate_baseline()
    if res.get("ok"):
        res["tree"] = coder_ws.tree(80)
    return res


# ── Memória de Projeto ────────────────────────────────────────────────────────

class ProjectAnalyzeRequest(BaseModel):
    path: str = ""  # vazio = usa o workspace atual do Coder


@app.post("/api/project/analyze")
async def project_analyze(req: ProjectAnalyzeRequest):
    """Detecta a stack e dependências do projeto e salva como contexto ativo.
    Se `path` estiver vazio, usa o workspace atual do Coder."""
    folder = (req.path or "").strip() or str(coder_ws.root)
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"Pasta não encontrada: {folder}"}
    ctx = await asyncio.to_thread(_analyze_project, folder)
    await asyncio.to_thread(project_mem.set_context, ctx)
    return {"ok": True, "context": ctx}


@app.get("/api/project/context")
async def project_context():
    """Retorna o contexto do projeto ativo (ou null se nenhum estiver ativo)."""
    ctx = project_mem.get_active() if project_mem else None
    return {"active": ctx}


@app.post("/api/project/clear")
async def project_clear():
    """Limpa o projeto ativo (A.P.O.L.O. para de usar o contexto de projeto)."""
    if project_mem:
        await asyncio.to_thread(project_mem.clear_active)
    return {"ok": True}


@app.get("/api/project/list")
async def project_list():
    """Lista todos os contextos de projeto salvos."""
    contexts = project_mem.list_all() if project_mem else []
    return {"contexts": contexts}


@app.delete("/api/project/{name}")
async def project_delete(name: str):
    """Remove um contexto de projeto salvo."""
    ok = await asyncio.to_thread(project_mem.remove, name) if project_mem else False
    return {"ok": ok}


@app.post("/api/coder/self")
async def coder_self_improve():
    """Aponta o Coder para o **próprio código do A.P.O.L.O.** (a pasta deste projeto),
    para que ele possa se automelhorar. Guiado pela doutrina em A.P.O.L.O._Code.md."""
    project_root = os.path.dirname(os.path.abspath(__file__))
    res = await asyncio.to_thread(coder_ws.set_root, project_root)
    if res.get("ok"):
        res["tree"] = coder_ws.tree(80)
        res["self"] = True
    return res


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
coder_sandbox_path: str | None = None  # cópia isolada ativa (ou None)


@app.post("/api/coder/sandbox")
async def coder_sandbox_create():
    """Cria uma CÓPIA isolada do projeto e aponta o Coder para ela. A automelhoria
    acontece na cópia — o projeto ao vivo só muda quando o usuário aplicar."""
    global coder_sandbox_path
    from src import sandbox
    if coder_sandbox_path:
        await asyncio.to_thread(sandbox.discard_sandbox, coder_sandbox_path)
    coder_sandbox_path = await asyncio.to_thread(sandbox.create_sandbox, PROJECT_ROOT)
    res = await asyncio.to_thread(coder_ws.set_root, coder_sandbox_path)
    res["sandbox"] = True
    res["tree"] = coder_ws.tree(80)
    return res


@app.get("/api/coder/sandbox/diff")
async def coder_sandbox_diff():
    """Lista as mudanças da cópia em relação ao projeto real."""
    from src import sandbox
    if not coder_sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    changes = await asyncio.to_thread(sandbox.diff_sandbox, coder_sandbox_path, PROJECT_ROOT)
    return {"ok": True, "changes": changes, "count": len(changes)}


@app.get("/api/coder/sandbox/file")
async def coder_sandbox_file(path: str):
    """Diff colorido de um arquivo (projeto real → cópia)."""
    from src import sandbox
    if not coder_sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    old, new = await asyncio.to_thread(sandbox.file_pair, coder_sandbox_path, PROJECT_ROOT, path)
    return {"ok": True, "diff": make_diff(old, new, path)["text"]}


class SandboxApplyRequest(BaseModel):
    paths: list[str] | None = None


@app.post("/api/coder/sandbox/apply")
async def coder_sandbox_apply(req: SandboxApplyRequest):
    """Aplica as mudanças da cópia ao projeto real (todas, ou só `paths`)."""
    global coder_sandbox_path
    from src import sandbox
    if not coder_sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    res = await asyncio.to_thread(sandbox.apply_sandbox, coder_sandbox_path, PROJECT_ROOT, req.paths)
    _invalidate_baseline()
    return res


@app.post("/api/coder/sandbox/discard")
async def coder_sandbox_discard():
    """Descarta a cópia e volta o Coder para o workspace isolado padrão."""
    global coder_sandbox_path
    from src import sandbox
    if coder_sandbox_path:
        await asyncio.to_thread(sandbox.discard_sandbox, coder_sandbox_path)
        coder_sandbox_path = None
    await asyncio.to_thread(coder_ws.set_root, os.path.join(PROJECT_ROOT, "workspace"))
    return {"ok": True}


@app.post("/api/coder/test-for")
async def coder_test_for(req: CoderPathRequest):
    """Detecta e roda testes relacionados a um arquivo do workspace.
    Retorna {ok, tests_found, total, passed, failed, skipped, results, output}."""
    path = (req.path or "").strip()
    if not path:
        return {"ok": False, "error": "path obrigatório"}
    related = await asyncio.to_thread(coder_ws.find_related_tests, path)
    if not related:
        return {"ok": True, "tests_found": [], "total": 0, "passed": 0,
                "failed": 0, "skipped": 0, "results": [], "output": ""}
    result = await asyncio.to_thread(coder_ws.run_tests_for, related)
    result["tests_found"] = related
    return result


@app.post("/api/coder/vscode")
async def coder_open_vscode(req: CoderPathRequest):
    """Abre o workspace do Coder (ou um arquivo `path`, opcionalmente `arquivo:linha`)
    no VS Code via CLI `code`."""
    return await asyncio.to_thread(coder_ws.open_in_vscode, req.path or "")


@app.get("/api/coder/browse")
async def coder_browse(path: str = ""):
    """Navegador de pastas do servidor — lista os subdiretórios de `path` para o
    usuário escolher o workspace. Só lista nomes de diretórios (read-only)."""
    def _list() -> dict:
        # Sem path → ponto de partida amigável: a pasta do projeto.
        base = path.strip() or os.path.dirname(os.path.abspath(__file__))
        try:
            base = os.path.abspath(base)
        except Exception:
            base = os.path.dirname(os.path.abspath(__file__))
        if not os.path.isdir(base):
            return {"ok": False, "error": f"não é uma pasta: {base}", "current": base, "dirs": []}
        try:
            _skip = {"__pycache__", "node_modules", ".git", ".venv", "venv"}
            entries = []
            for name in sorted(os.listdir(base), key=str.lower):
                full = os.path.join(base, name)
                if os.path.isdir(full) and not name.startswith(".") and name not in _skip:
                    entries.append({"name": name, "path": full})
        except PermissionError:
            return {"ok": False, "error": "sem permissão para ler esta pasta",
                    "current": base, "dirs": []}
        parent = os.path.dirname(base)
        return {"ok": True, "current": base,
                "parent": parent if parent and parent != base else "",
                "dirs": entries}
    return await asyncio.to_thread(_list)


def _parse_agent_action(content: str) -> tuple[str, str]:
    """Decide a ação do agente a partir da resposta do modelo (ReAct).
    Retorna (tipo, payload): 'code' | 'web' | 'base' | 'final'."""
    code = extract_code(content)
    if code and "```" in content:
        return "code", code
    import re
    for line in content.splitlines():
        m = re.match(r"\s*BUSCAR_WEB:\s*(.+)", line, re.IGNORECASE)
        if m and len(m.group(1).strip()) >= 3:
            return "web", m.group(1).strip()
        m = re.match(r"\s*CONSULTAR_BASE:\s*(.+)", line, re.IGNORECASE)
        if m and len(m.group(1).strip()) >= 3:
            return "base", m.group(1).strip()
    return "final", content


def _clean_agent_answer(text: str) -> str:
    """Remove vazamentos de scaffolding que modelos leves às vezes ecoam
    (ex.: 'RESPOSTA FINAL:', 'RESPOSTAR:', 'APENAS com a versão...')."""
    import re
    t = (text or "").strip()
    # Tolera markdown/pontuação antes do rótulo (ex.: '**RESPOSTA FINAL:**', '### RESPOSTA:').
    lead = r"^[\s*#>_`-]*"
    t = re.sub(lead + r"(RESPOSTA\s*FINAL|RESPOSTAR?|RESPOSTA)\s*:?[\s*]*", "", t, flags=re.IGNORECASE)
    t = re.sub(lead + r"APENAS com a vers[ãa]o[^\n:]*:?[\s*]*", "", t, flags=re.IGNORECASE)
    # Corta uma eventual cauda em que o modelo recomeça a ecoar o prompt de avaliação.
    t = re.split(r"\n\s*Avalie\s*:", t, maxsplit=1, flags=re.IGNORECASE)[0]
    return t.strip()


async def _agent_recall(query: str, limit: int = 3) -> str:
    """Memória de longo prazo do agente — soluções/conhecimento já produzidos (RAG)."""
    if not rag:
        return ""
    try:
        hits = await asyncio.to_thread(rag.recall, query, limit)
    except Exception:
        return ""
    parts = []
    for h in hits or []:
        if h.get("relevance") is not None and h["relevance"] < 0.15:
            continue
        title = h.get("title") or "memória"
        parts.append(f"**{title}**\n{(h.get('snippet') or '')[:400]}")
    return "\n\n---\n\n".join(parts)


@app.post("/api/agent")
async def agent(req: ChatRequest):
    """Modo Agente (ReAct-lite): o A.P.O.L.O. escreve código Python, EXECUTA de
    verdade e usa o resultado real para responder — cálculos/lógica ficam exatos."""
    global _last_request_at
    _last_request_at = _time.perf_counter()
    question = sanitize_request(req.message)
    if learner:
        learner.add_user_topic(question)
    history = _get_session(req.session_id)
    model = CHAT_MODEL  # qwen2.5-coder escreve código muito bem mesmo no leve

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        answer = ""
        try:
            system_content = SYSTEM_PROMPT + AGENT_INSTRUCTION
            if profile:
                facts = profile.as_context()
                if facts:
                    system_content += PERSONAL_SECTION.format(facts=facts)

            # ── (2) Memória de longo prazo: recupera soluções/conhecimento já produzidos ──
            yield _ev({"type": "step", "icon": "🧠", "message": "Consultando memória de longo prazo..."})
            mem = await _agent_recall(question)
            if mem:
                system_content += AGENT_MEMORY_SECTION.format(context=mem)

            messages = [{"role": "system", "content": system_content}]
            messages.extend(history[-MAX_HISTORY:])
            messages.append({"role": "user", "content": question})

            # ── Loop ReAct iterativo: pensar → (executar | buscar web | consultar base) → responder ──
            fixes = 0          # tentativas de correção de erro
            used_tools = False # houve execução/busca/consulta (define se vale salvar/avaliar)
            had_code = False   # houve execução de código (resultado é verdade-base, não reescrever)
            answer = ""
            for step in range(MAX_AGENT_STEPS):
                msg = ("Raciocinando..." if step == 0 else
                       "Analisando o resultado e decidindo o próximo passo...")
                yield _ev({"type": "step", "icon": "🤖", "message": msg})
                content = await asyncio.to_thread(
                    chat_resilient, model, messages, keep_alive=KEEP_ALIVE,
                ) or ""
                action, payload = _parse_agent_action(content)

                if action == "final":
                    answer = content
                    break

                messages.append({"role": "assistant", "content": content})

                # ── (1) Ferramenta: executar código ──
                if action == "code":
                    used_tools = True
                    had_code = True
                    label = "Executando o código..." if fixes == 0 else f"Corrigindo e re-executando (tentativa {fixes + 1})..."
                    yield _ev({"type": "step", "icon": "🔧", "message": label})
                    exec_result = await asyncio.to_thread(executor.run, payload)
                    if exec_result.success:
                        out = (exec_result.stdout or "").strip()[:1500]
                        yield _ev({"type": "step", "icon": "✓", "message": f"Saída: {out[:160] or '(vazia)'}"})
                        messages.append({"role": "user", "content":
                            f"Saída real da execução:\n```\n{out}\n```\n"
                            "Se isto resolve o pedido, escreva a RESPOSTA FINAL (sem código/ações). "
                            "Senão, faça a próxima ação."})
                    else:
                        fixes += 1
                        err = (exec_result.stderr or exec_result.stdout or "").strip()[:1500]
                        yield _ev({"type": "step", "icon": "✗", "message": f"Erro: {err[:160] or '(desconhecido)'} — vou corrigir"})
                        if fixes > MAX_AGENT_FIXES:
                            messages.append({"role": "user", "content":
                                f"O código falhou de novo:\n```\n{err}\n```\nNão tente mais código. "
                                "Explique o que deu errado e dê a melhor resposta possível."})
                        else:
                            messages.append({"role": "user", "content": FIX_PROMPT.format(code=payload, error=err)})

                # ── (1) Ferramenta: buscar na web ──
                elif action == "web":
                    used_tools = True
                    yield _ev({"type": "step", "icon": "🌐", "message": f"Buscando na web: {payload[:80]}"})
                    try:
                        web_ctx, srcs = await asyncio.wait_for(web_research(payload, max_results=3), timeout=20.0)
                    except Exception:
                        web_ctx, srcs = "", []
                    obs = (web_ctx or "Nenhum resultado encontrado.")[:1800]
                    yield _ev({"type": "step", "icon": "✓" if web_ctx else "✗",
                               "message": f"{len(srcs)} fontes" if srcs else "sem resultados"})
                    messages.append({"role": "user", "content":
                        f"Resultado da busca na web por '{payload}':\n{obs}\n\nUse isto. Próxima ação ou RESPOSTA FINAL."})

                # ── (1)+(2) Ferramenta: consultar a base/memória ──
                elif action == "base":
                    used_tools = True
                    yield _ev({"type": "step", "icon": "📚", "message": f"Consultando a base: {payload[:80]}"})
                    found = await _agent_recall(payload, limit=4)
                    obs = found or "Nada relevante na base."
                    yield _ev({"type": "step", "icon": "✓" if found else "✗",
                               "message": "encontrado" if found else "nada na base"})
                    messages.append({"role": "user", "content":
                        f"O que você já sabe sobre '{payload}':\n{obs}\n\nUse isto. Próxima ação ou RESPOSTA FINAL."})

            # Esgotou os passos sem resposta final → força uma resposta com o que tem.
            if not answer:
                messages.append({"role": "user", "content":
                    "Responda agora ao usuário com o que você já tem, em português e SEM código/ações."})
                answer = await asyncio.to_thread(chat_resilient, model, messages, keep_alive=KEEP_ALIVE) or "Não consegui concluir."

            answer = _clean_agent_answer(answer)

            # ── (3) Auto-avaliação: critica e refina a própria resposta (1 passe).
            # NUNCA reescreve resultado vindo de código — a saída executada é verdade-base
            # e um modelo leve poderia corromper o número. Só refina respostas de texto/web.
            if AGENT_SELF_EVAL and used_tools and not had_code and answer.strip():
                yield _ev({"type": "step", "icon": "🔎", "message": "Revisando a própria resposta..."})
                try:
                    crit = await asyncio.to_thread(
                        chat_resilient, model,
                        [{"role": "user", "content": AGENT_SELFEVAL_PROMPT.format(question=question, answer=answer)}],
                        keep_alive=KEEP_ALIVE,
                    )
                    verdict = _clean_agent_answer(crit or "")
                    if verdict and verdict.upper() != "OK" and not verdict.upper().startswith("OK") and len(verdict) > 15:
                        answer = verdict  # adotou a versão refinada
                        yield _ev({"type": "step", "icon": "✨", "message": "Resposta refinada após autocrítica"})
                except Exception as e:
                    logger.debug(f"self-eval: {e}")

            # Emite a resposta final.
            yield _ev({"type": "token", "content": answer})

            # ── (2) Memória de longo prazo: guarda a solução para uso futuro ──
            if rag and used_tools and answer.strip():
                try:
                    doc_id = f"agent_solution_{hash(question.strip().lower()) & 0xFFFFFFFF:08x}"
                    await asyncio.to_thread(
                        rag.add_example,
                        f"# [SOLUÇÃO] {question[:120]}\nFonte: agente\n\n{answer[:2000]}", doc_id,
                    )
                except Exception as e:
                    logger.debug(f"save solution: {e}")

            # Persiste a conversa (igual ao chat).
            is_first = len(sessions[req.session_id]) == 0
            sessions[req.session_id].append({"role": "user", "content": question})
            sessions[req.session_id].append({"role": "assistant", "content": answer})
            db.save_message(req.session_id, "user", question)
            db.save_message(req.session_id, "assistant", answer)
            if is_first:
                asyncio.create_task(_generate_session_title(req.session_id, question))
            yield _ev({"type": "done", "answer": answer})
        except Exception as e:
            logger.error(f"Erro no agente: {e}", exc_info=True)
            yield _ev({"type": "error", "message": str(e)})

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/orchestrate")
async def orchestrate_endpoint(req: ChatRequest):
    """Orquestrador de sub-agentes — decompõe tarefas complexas, delega a
    especialistas (Researcher / Analyst / Coder) e sintetiza a resposta final.
    Streaming SSE com eventos: step, agent_start, agent_token, done."""
    global _last_request_at
    _last_request_at = _time.perf_counter()
    task = sanitize_request(req.message)
    if learner:
        learner.add_user_topic(task)

    from src.orchestrator import orchestrate

    async def stream():
        try:
            async for ev in orchestrate(
                task=task,
                chat_model=CHAT_MODEL,
                heavy_model=MODEL,
                keep_light=KEEP_ALIVE,
                keep_heavy=KEEP_ALIVE_HEAVY,
                rag=rag,
                knowledge_db=knowledge_db,
            ):
                yield f"data: {json.dumps(ev)}\n\n"

            # Persiste a conversa na sessão
            # (pega a resposta do último evento 'done' na transmissão — já foi enviado)
        except Exception as e:
            logger.error(f"orchestrate: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        _gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/benchmark/run")
async def benchmark_run():
    """Executa o benchmark de qualidade, persiste no banco e retorna métricas."""
    from src.benchmark import run_benchmark
    result = await run_benchmark(chat_model=CHAT_MODEL, keep_alive=KEEP_ALIVE)
    result["timestamp"] = datetime.now().isoformat()
    # Persiste no banco (sobrevive ao restart) + memória (acesso rápido)
    await asyncio.to_thread(db.save_benchmark_run, result)
    _benchmark_history.append(result)
    if len(_benchmark_history) > _BENCHMARK_HISTORY_MAX:
        _benchmark_history.pop(0)
    return result


@app.get("/api/benchmark/history")
async def benchmark_history():
    """Histórico de benchmark — banco (persistente) + memória desta sessão."""
    saved = await asyncio.to_thread(db.get_benchmark_history, 20)
    return {"runs": len(saved), "history": saved}


@app.get("/api/analytics")
async def analytics():
    """Painel de analytics: uso, perguntas mais frequentes, tópicos, benchmark."""
    summary, by_day, by_hour, top_topics, top_words, bench = await asyncio.gather(
        asyncio.to_thread(db.analytics_usage_summary),
        asyncio.to_thread(db.analytics_messages_by_day, 30),
        asyncio.to_thread(db.analytics_messages_by_hour),
        asyncio.to_thread(db.analytics_top_topics, 20),
        asyncio.to_thread(db.analytics_top_words, 15),
        asyncio.to_thread(db.get_benchmark_history, 10),
    )
    return {
        "summary": summary,
        "messages_by_day": by_day,
        "messages_by_hour": by_hour,
        "top_topics": top_topics,
        "top_words": top_words,
        "benchmark_history": bench,
    }


class ReactionRequest(BaseModel):
    message_hash: str
    reaction: str           # "up" ou "down"
    session_id: str = ""
    sources: list[str] = []


@app.post("/api/reactions")
async def save_reaction(req: ReactionRequest):
    """#7 Salva feedback 👍/👎 no banco. Alimenta métricas de qualidade."""
    await asyncio.to_thread(
        db.save_reaction, req.message_hash, req.reaction, req.session_id, req.sources
    )
    return {"ok": True}


@app.get("/api/reactions/stats")
async def reaction_stats():
    """Estatísticas de reações — total, taxa positiva, fontes mais negativas."""
    return await asyncio.to_thread(db.reaction_stats)


@app.get("/api/benchmark/diff")
async def benchmark_diff():
    """Compara os dois últimos runs: delta de score e latência por pergunta."""
    from src.benchmark import diff_runs
    if len(_benchmark_history) < 2:
        return {"ok": False, "error": "São necessários pelo menos 2 runs para comparar"}
    return {"ok": True, **diff_runs(_benchmark_history[-2], _benchmark_history[-1])}


class IngestRequest(BaseModel):
    filename: str
    content: str
    encoding: str = "text"  # "text" (texto/código) | "base64" (PDF e binários)


@app.post("/api/ingest")
async def ingest_document(req: IngestRequest):
    """Ingere um documento do usuário na memória (ChromaDB + Supabase).
    Depois disso o A.P.O.L.O. responde sobre ele e o cita no chat."""
    if not ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}
    filename = (req.filename or "documento").strip()[:120]
    try:
        if req.encoding == "base64":
            import base64
            data = base64.b64decode(req.content)
            if filename.lower().endswith(".pdf"):
                try:
                    from src.ingest import extract_pdf_text
                    text = await asyncio.to_thread(extract_pdf_text, data)
                except ModuleNotFoundError:
                    return {"ok": False, "error": "Suporte a PDF requer: pip install pypdf"}
            elif filename.lower().endswith(".docx"):
                try:
                    from src.ingest import extract_docx_text
                    text = await asyncio.to_thread(extract_docx_text, data)
                except ModuleNotFoundError:
                    return {"ok": False, "error": "Suporte a DOCX requer: pip install python-docx"}
            else:
                text = data.decode("utf-8", errors="ignore")
        else:
            text = req.content
    except Exception as e:
        logger.warning(f"Ingest decode error: {e}")
        return {"ok": False, "error": f"Falha ao ler o arquivo: {e}"}

    result = await asyncio.to_thread(ingestor.ingest_text, filename, text)
    return result


class IngestUrlRequest(BaseModel):
    url: str


@app.post("/api/ingest/url")
async def ingest_url(req: IngestUrlRequest):
    """Aprende a partir de um link: busca a página e a ingere como um documento."""
    if not ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "Informe uma URL http(s) válida."}
    try:
        from src.web_search import fetch_page_text
        text = await asyncio.wait_for(fetch_page_text(url), timeout=20.0)
    except Exception as e:
        logger.warning(f"Ingest URL fetch error: {e}")
        return {"ok": False, "error": "Não consegui buscar essa página."}
    if not text or len(text) < 50:
        return {"ok": False, "error": "A página não tem conteúdo de texto suficiente."}

    from urllib.parse import urlparse
    name = (urlparse(url).netloc or url)[:120]
    result = await asyncio.to_thread(ingestor.ingest_text, name, text, url)
    result["source_url"] = url
    return result


class IngestFolderRequest(BaseModel):
    path: str
    extensions: list[str] = [".md", ".txt", ".markdown"]
    max_files: int = 200


@app.post("/api/ingest/folder")
async def ingest_folder(req: IngestFolderRequest):
    """Importa todos os arquivos de texto de uma pasta local (ex.: vault Obsidian).
    Percorre recursivamente, ingere cada arquivo .md/.txt no RAG e retorna o resumo."""
    if not ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}

    folder = req.path.strip()
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"Pasta não encontrada: {folder}"}

    # Coleta arquivos com as extensões pedidas
    _SKIP = {"__pycache__", ".git", "node_modules", ".obsidian"}
    files: list[str] = []
    for root, dirs, fnames in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for fname in sorted(fnames):
            if any(fname.lower().endswith(ext) for ext in req.extensions):
                files.append(os.path.join(root, fname))
                if len(files) >= req.max_files:
                    break
        if len(files) >= req.max_files:
            break

    if not files:
        return {"ok": False, "error": "Nenhum arquivo encontrado com as extensões pedidas."}

    # Ingere cada arquivo
    ok_count = 0
    skip_count = 0
    errors: list[str] = []

    def _ingest_file(fpath: str) -> dict:
        try:
            content = open(fpath, encoding="utf-8", errors="ignore").read()
            filename = os.path.relpath(fpath, folder).replace("\\", "/")
            source = f"obsidian://{filename}"
            return ingestor.ingest_text(filename, content, source)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    for fpath in files:
        res = await asyncio.to_thread(_ingest_file, fpath)
        if res.get("ok"):
            ok_count += 1
        else:
            skip_count += 1
            if res.get("error"):
                errors.append(res["error"])

    return {
        "ok": True,
        "folder": folder,
        "total_files": len(files),
        "ingested": ok_count,
        "skipped": skip_count,
        "errors": errors[:5],
    }


class RepoRequest(BaseModel):
    url: str


@app.post("/api/repo/analyze")
async def repo_analyze(req: RepoRequest):
    """Clona um repositório GitHub público, percorre todos os arquivos de texto
    e indexa no RAG com metadados (repo, file_path, owner). Streaming SSE com
    progresso em tempo real. Após concluir, o A.P.O.L.O. responde perguntas
    sobre qualquer arquivo do repositório."""
    from src.repo_indexer import analyze_repo as _analyze_repo

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        try:
            async for ev in _analyze_repo(req.url.strip(), rag):
                yield _ev(ev)
                if ev.get("type") == "done" and learner:
                    learner.add_user_topic(f"repositório GitHub: {ev.get('repo_name','')}")
        except Exception as e:
            logger.error(f"repo_analyze: {e}", exc_info=True)
            yield _ev({"type": "error", "message": str(e)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/repo/list")
async def repo_list():
    """Lista os repositórios indexados no RAG (doc_ids que começam com 'repo_')."""
    if not rag:
        return {"repos": []}
    try:
        data = rag.collection.get(where={"type": {"$eq": "repo_file"}},
                                  include=["metadatas"], limit=1000)
        repos: dict[str, dict] = {}
        for meta in (data.get("metadatas") or []):
            if meta and meta.get("repo"):
                name = meta["repo"]
                if name not in repos:
                    repos[name] = {"name": name, "url": meta.get("repo_url", ""),
                                   "files": 0}
                repos[name]["files"] += 1
        return {"repos": list(repos.values())}
    except Exception as e:
        logger.warning(f"repo_list: {e}")
        return {"repos": []}


@app.post("/api/stt")
async def stt_transcribe(request: Request):
    """Transcrição de voz local via faster-whisper.
    Recebe o áudio bruto (WebM/WAV) como body da requisição.
    Se faster-whisper não estiver instalado, retorna {ok:false} e o frontend
    usa o fallback Web Speech API do navegador."""
    from src.whisper_stt import transcribe, is_available
    if not is_available():
        return {"ok": False, "error": "faster-whisper não instalado",
                "hint": "pip install faster-whisper"}
    audio = await request.body()
    if len(audio) < 100:
        return {"ok": False, "error": "Áudio muito curto ou vazio"}
    size = os.getenv("WHISPER_MODEL", "base")
    text = await asyncio.to_thread(transcribe, audio, size)
    if text:
        return {"ok": True, "text": text}
    return {"ok": False, "error": "Não foi possível transcrever o áudio"}


@app.get("/api/tts")
async def tts_endpoint(text: str = "", voice: str = "pt-BR-FranciscaNeural"):
    """TTS de alta qualidade via edge-tts (vozes neurais PT-BR).
    Retorna áudio MP3 em streaming — o frontend toca via Audio API.
    Fallback: speechSynthesis do navegador (browser) quando não instalado."""
    from src.tts import is_available, synthesize
    if not is_available():
        return JSONResponse({"error": "edge-tts não instalado", "hint": "pip install edge-tts"},
                            status_code=503)
    clean = (text or "").strip()
    if not clean:
        return JSONResponse({"error": "texto vazio"}, status_code=400)
    return StreamingResponse(
        synthesize(clean, voice),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/curate/scan")
async def curate_scan():
    """Relatório (só leitura) de conhecimento duplicado (base + recall + log)."""
    if not curator:
        return {"enabled": False, "total": 0, "duplicate_clusters": 0, "removable": 0,
                "chroma_duplicates": 0, "log_duplicates": 0, "clusters": []}
    data = await asyncio.to_thread(curator.scan)
    return {"enabled": True, **data}


class CurateApply(BaseModel):
    ids: list[str]


@app.post("/api/curate/apply")
async def curate_apply(req: CurateApply):
    """Remove as duplicatas indicadas (ação explícita do usuário)."""
    if not curator:
        return {"ok": False, "error": "Curador indisponível."}
    return await asyncio.to_thread(curator.apply, req.ids)


@app.get("/api/profile")
async def get_profile():
    """Lista os fatos que o A.P.O.L.O. sabe sobre o usuário."""
    return {"facts": profile.list() if profile else []}


class FactRequest(BaseModel):
    fact: str


@app.post("/api/profile")
async def add_fact(req: FactRequest):
    if not profile:
        return {"ok": False, "error": "Perfil indisponível."}
    item = profile.add(req.fact)
    if item:
        _syscache_inv()  # perfil mudou → system prompt stale em todas as sessões
    return {"ok": bool(item), "fact": item}


@app.delete("/api/profile/{fact_id}")
async def remove_fact(fact_id: str):
    if not profile:
        return {"ok": False}
    return {"ok": profile.remove(fact_id)}


@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    sessions.pop(session_id, None)
    db.delete_session(session_id)
    return {"ok": True}


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Carrega conversa completa de uma sessão para restaurar no front."""
    msgs = db.load_session(session_id)
    return {"session_id": session_id, "messages": msgs}


@app.get("/api/sessions")
async def list_sessions():
    """Lista todas as sessões (chats antigos inclusos) para a sidebar."""
    return db.list_sessions(days=0, limit=100)


@app.get("/api/session/{session_id}/export")
async def export_session_md(session_id: str):
    """Baixa a conversa como arquivo Markdown."""
    md = await asyncio.to_thread(db.export_session_markdown, session_id)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([md]), media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="apolo_conversa_{stamp}.md"'},
    )


@app.get("/api/sessions/search")
async def search_sessions(q: str = ""):
    """Busca no histórico de conversas (todos os chats) por trecho de texto."""
    results = await asyncio.to_thread(db.search_messages, q, 30)
    return {"query": q, "results": results}


@app.post("/api/sessions/reindex")
async def reindex_sessions():
    """Indexa (ou re-indexa) todas as conversas históricas na memória episódica
    (ChromaDB). Use para aproveitar chats antigos no recall semântico do chat."""
    if not rag:
        return {"ok": False, "error": "RAG não inicializado"}
    sessions_list = await asyncio.to_thread(db.list_sessions, 0, 500)
    indexed, skipped = 0, 0
    for sess in sessions_list:
        sid = sess["session_id"]
        title = sess.get("title") or sess.get("first_message", "")[:60]
        messages = await asyncio.to_thread(db.load_session, sid)
        summ = session_summaries.get(sid, {}).get("text", "")
        ok = await asyncio.to_thread(_index_episodic, sid, title, messages, rag, summ)
        if ok:
            indexed += 1
        else:
            skipped += 1
    return {"ok": True, "indexed": indexed, "skipped": skipped,
            "total": len(sessions_list)}


@app.get("/api/export/obsidian")
async def export_obsidian():
    """Exporta todo o conhecimento acumulado como vault Obsidian (ZIP de .md).

    Gera um arquivo por setor com todos os tópicos aprendidos, links internos
    entre tópicos relacionados e um índice geral. Abra o ZIP descompactado
    como vault no Obsidian para navegar pelo conhecimento do A.P.O.L.O."""
    from src.obsidian import generate_vault
    zip_bytes = await asyncio.to_thread(generate_vault, db, knowledge_db)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="APOLO_Obsidian_{stamp}.zip"'},
    )


@app.get("/api/export")
async def export_all():
    """Backup completo: conhecimento (Supabase) + sessões e tópicos (SQLite) em JSON."""
    data = await asyncio.to_thread(db.export_all)
    if knowledge_db:
        try:
            data["knowledge"] = await asyncio.to_thread(knowledge_db.all_rows, 5000)
            data["counts"]["knowledge"] = len(data["knowledge"])
        except Exception as e:
            logger.warning(f"export knowledge: {e}")
            data["knowledge"] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="apolo_backup_{stamp}.json"'},
    )


@app.post("/api/import")
async def import_backup(request: Request):
    """Restaura um backup do /api/export (idempotente). Recria sessões, mensagens,
    tópicos aprendidos e — se o Supabase estiver ativo — o conhecimento."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "JSON inválido"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "formato inesperado"}

    added = await asyncio.to_thread(db.import_all, data)

    knowledge_restored = 0
    if knowledge_db and isinstance(data.get("knowledge"), list):
        def _restore_knowledge(rows):
            n = 0
            for r in rows:
                if not r.get("url"):
                    continue
                knowledge_db.save(
                    r.get("title") or "(sem título)", r["url"],
                    r.get("content") or "", r.get("category") or "web", r.get("tags") or [],
                )
                n += 1
            return n
        try:
            knowledge_restored = await asyncio.to_thread(_restore_knowledge, data["knowledge"])
        except Exception as e:
            logger.warning(f"import knowledge: {e}")

    # Limpa o cache em memória para refletir o que foi importado.
    sessions.clear()
    return {"ok": True, "added": added, "knowledge_restored": knowledge_restored}


class ScheduleRequest(BaseModel):
    topic: str
    time_of_day: str = "08:00"


@app.get("/api/schedules")
async def list_schedules():
    """Lista os estudos agendados."""
    return db.list_schedules()


@app.post("/api/schedules")
async def add_schedule(req: ScheduleRequest):
    """Agenda um estudo diário: o A.P.O.L.O. estuda `topic` todo dia às `time_of_day`."""
    topic = (req.topic or "").strip()
    t = (req.time_of_day or "").strip()
    # Validação simples de HH:MM
    import re
    if len(topic) < 3:
        return {"ok": False, "error": "tópico muito curto"}
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t):
        return {"ok": False, "error": "horário inválido (use HH:MM)"}
    row = await asyncio.to_thread(db.add_schedule, topic, t)
    return {"ok": True, "schedule": row}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    ok = await asyncio.to_thread(db.delete_schedule, schedule_id)
    return {"ok": ok}


@app.post("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    ok = await asyncio.to_thread(db.toggle_schedule, schedule_id)
    return {"ok": ok}


@app.get("/api/notifications")
async def list_notifications():
    """Avisos do A.P.O.L.O. (autonomia visível) + contador de não-lidas."""
    items = await asyncio.to_thread(db.list_notifications, 30, False)
    unread = await asyncio.to_thread(db.unread_count)
    return {"items": items, "unread": unread}


@app.post("/api/notifications/read")
async def read_notifications():
    n = await asyncio.to_thread(db.mark_notifications_read)
    return {"ok": True, "marked": n}


@app.delete("/api/notifications")
async def clear_notifications():
    n = await asyncio.to_thread(db.clear_notifications)
    return {"ok": True, "cleared": n}


@app.get("/api/perf")
async def perf_metrics():
    """Telemetria de latência por endpoint (média, p95, máximo, contagem, erros).
    Para flagrar regressões de performance — ex.: se a Mente voltar a ficar lenta."""
    return perf_tracker.snapshot()


@app.post("/api/perf/reset")
async def perf_reset():
    perf_tracker.reset()
    return {"ok": True}


@app.get("/api/boot")
async def boot_data():
    """Dados de inicialização do frontend — agrega o que antes eram 6+ chamadas separadas.
    Retorna em paralelo: modelos, estado Supabase, status do aprendizado, notificações
    não lidas e sessões recentes. Reduz o tempo de carregamento da UI."""
    from src.providers import get_provider

    async def _models():
        try:
            installed = get_provider().list_models()
            return {"chat_model": CHAT_MODEL, "heavy_model": MODEL,
                    "vision_model": VISION_MODEL, "installed": installed}
        except Exception:
            return {"chat_model": CHAT_MODEL, "heavy_model": MODEL,
                    "vision_model": VISION_MODEL, "installed": []}

    async def _kb_stats():
        if not knowledge_db:
            return {"enabled": False, "total": 0}
        try:
            return {"enabled": True, **await asyncio.to_thread(knowledge_db.stats)}
        except Exception:
            return {"enabled": True, "total": 0}

    async def _learn():
        return learner.get_status() if learner else {"running": False}

    async def _notifs():
        try:
            return await asyncio.to_thread(db.unread_count)
        except Exception:
            return 0

    async def _sessions():
        try:
            return await asyncio.to_thread(db.list_sessions, 0, 100)
        except Exception:
            return []

    models_r, kb_r, learn_r, notifs_r, sess_r = await asyncio.gather(
        _models(), _kb_stats(), _learn(), _notifs(), _sessions()
    )

    proj = project_mem.get_active() if project_mem else None

    from src.system_cache import stats as _sc_stats
    from src.whisper_stt import is_available as _stt_ok
    from src.tts import is_available as _tts_ok

    return {
        "ok": True,
        "models": models_r,
        "knowledge": kb_r,
        "learner": learn_r,
        "unread_notifications": notifs_r,
        "sessions": sess_r,
        "active_project": proj,
        "stt": _stt_ok(),
        "tts_engine": "edge-tts" if _tts_ok() else "browser",
        "system_cache": _sc_stats(),
    }


@app.get("/api/health")
async def health():
    """Painel de saúde — estado consolidado do A.P.O.L.O. num só lugar.
    Os blocos são independentes e fazem I/O de rede (Ollama, Supabase, embeddings),
    então rodam em paralelo (`asyncio.gather`) — antes era tudo sequencial."""
    out: dict = {"ok": True}

    async def _ollama():
        from src.providers import get_provider
        try:
            models = await asyncio.to_thread(get_provider().list_models)
        except Exception as e:
            return {"installed": [], "_error": str(e)[:120], "chat_model": CHAT_MODEL,
                    "heavy_model": MODEL, "vision_model": VISION_MODEL, "has_vision": bool(VISION_MODEL)}
        from src.hardware import summary as _hw_summary
        return {"installed": models, "chat_model": CHAT_MODEL, "heavy_model": MODEL,
                "vision_model": VISION_MODEL, "has_vision": bool(VISION_MODEL),
                "backend": get_provider().name, "breaker": ollama_breaker_state(),
                "hardware": _hw_summary()}

    async def _database():
        try:
            ls = await asyncio.to_thread(db.get_learning_stats)
            dups, sess = await asyncio.gather(
                asyncio.to_thread(db.count_topic_duplicates),
                asyncio.to_thread(db.list_sessions, 0, 1000),
            )
            return {"learned_total": ls["total"], "learned_today": ls["today"],
                    "duplicates": dups, "sessions": len(sess)}
        except Exception as e:
            return {"error": str(e)[:120]}

    async def _supabase():
        if not knowledge_db:
            return {"enabled": False}
        try:
            stats = await asyncio.to_thread(knowledge_db.stats)
            return {"enabled": True, "breaker": knowledge_db.breaker_state(), **stats}
        except Exception as e:
            return {"enabled": True, "error": str(e)[:120],
                    "breaker": knowledge_db.breaker_state()}

    async def _recall():
        if not rag:
            return None
        try:
            recent = await asyncio.to_thread(db.get_learned_since, 720, 8)  # ~30 dias
            sample = [r["topic"] for r in recent][:6]
            if not sample:
                sample = [r["topic"] for r in await asyncio.to_thread(db.get_learning_history, 6)]
            return await asyncio.to_thread(rag.recall_quality, sample)
        except Exception as e:
            return {"error": str(e)[:120]}

    ollama_r, db_r, supa_r, recall_r = await asyncio.gather(
        _ollama(), _database(), _supabase(), _recall())
    if "_error" in ollama_r:
        out["ollama_error"] = ollama_r.pop("_error")
    out["ollama"] = ollama_r
    out["database"] = db_r
    out["supabase"] = supa_r
    if recall_r is not None:
        out["recall"] = recall_r

    # Aprendizado contínuo (local, rápido)
    if learner:
        st = learner.get_status()
        out["learner"] = {
            "running": st.get("running"),
            "queue_depth": st.get("queue_depth"),
            "total_session": st.get("total_session"),
            "throughput_hour": st.get("throughput_hour"),
            "gap_count": st.get("gap_count"),
            "active_agents": [a for a in st.get("agents", []) if a.get("active")],
        }
    else:
        out["learner"] = {"running": False}

    # STT local (Whisper), TTS (edge-tts) e ingestão de documentos
    from src.whisper_stt import is_available as _stt_available
    from src.tts import is_available as _tts_available, VOICES as _tts_voices
    out["stt"] = _stt_available()
    out["tts_engine"] = "edge-tts" if _tts_available() else "browser"
    out["tts_voices"] = list(_tts_voices.keys()) if _tts_available() else []
    out["features"] = {
        "docx": True,
        "pdf": True,
        "whisper": out["stt"],
        "edge_tts": _tts_available(),
        "hands_free": True,
        "drag_drop": True,
    }

    # Backend de conhecimento (Supabase ou LocalKnowledge)
    kb_backend = "none"
    if knowledge_db is not None:
        from src.local_knowledge import LocalKnowledge
        kb_backend = "local_sqlite" if isinstance(knowledge_db, LocalKnowledge) else "supabase"
    out["knowledge_backend"] = kb_backend

    return out


@app.get("/api/history")
async def history():
    return db.get_history(limit=50)


class ForgetRequest(BaseModel):
    id: int


@app.post("/api/knowledge/forget")
async def knowledge_forget(req: ForgetRequest):
    """Esquece um conhecimento: remove do log (SQLite), do Supabase e do RAG."""
    info = await asyncio.to_thread(db.delete_learned_topic, req.id)
    if not info:
        return {"ok": False, "error": "não encontrado"}
    removed = {"sqlite": True, "supabase": 0, "rag": 0}
    if knowledge_db and info.get("url"):
        removed["supabase"] = await asyncio.to_thread(knowledge_db.delete_by_url, info["url"])
    if rag and info.get("topic"):
        removed["rag"] = await asyncio.to_thread(rag.forget_topic, info["topic"])
    return {"ok": True, "topic": info["topic"], "removed": removed}


@app.get("/api/knowledge/stats")
async def knowledge_stats():
    if not knowledge_db:
        return {"enabled": False, "total": 0}
    stats = await asyncio.to_thread(knowledge_db.stats)
    return {"enabled": True, **stats}


@app.get("/api/knowledge/graph")
async def knowledge_graph():
    """Mapa de conhecimento: centro (A.P.O.L.O.) → setores → tópicos de exemplo.
    Monta um grafo a partir dos tópicos aprendidos, agrupados por setor."""
    from src.topics import classify_sector, SECTOR_LABELS

    # Cache curto: o mapa muda devagar (só com novos estudos) e era reconstruído
    # do zero a cada abertura do painel.
    import time
    cache = knowledge_graph._cache
    if cache and (time.time() - cache[0]) < 60:
        return cache[1]

    def _build() -> dict:
        history = db.get_learning_history(limit=400) if db else []
        groups: dict[str, list[str]] = {}
        for h in history:
            topic = (h.get("topic") or "").strip()
            if not topic:
                continue
            sec = classify_sector(topic)
            groups.setdefault(sec, [])
            if len(groups[sec]) < 5:
                groups[sec].append(topic[:60])
        # Ordena setores por volume e limita para o mapa não virar sopa.
        ranked = sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
        nodes = [{"id": "apolo", "label": "A.P.O.L.O.", "type": "core"}]
        edges = []
        for sec, topics in ranked:
            sid = f"sec::{sec}"
            nodes.append({"id": sid, "label": SECTOR_LABELS.get(sec, sec),
                          "type": "sector", "sector": sec, "count": len(topics)})
            edges.append({"source": "apolo", "target": sid})
            for i, t in enumerate(topics[:4]):
                tid = f"{sid}::t{i}"
                nodes.append({"id": tid, "label": t, "type": "topic"})
                edges.append({"source": sid, "target": tid})
        return {"nodes": nodes, "edges": edges, "sectors": len(ranked)}

    try:
        result = await asyncio.to_thread(_build)
        knowledge_graph._cache = (time.time(), result)
        return result
    except Exception as e:
        logger.warning(f"knowledge_graph: {e}")
        return {"nodes": [], "edges": [], "sectors": 0}


knowledge_graph._cache = None  # (timestamp, payload) — cache curto do mapa


@app.get("/api/knowledge/insights")
async def knowledge_insights():
    """Auto-percepção do A.P.O.L.O. — o que ele sabe + estado vivo do aprendizado.
    Alimenta o painel 'Mente do A.P.O.L.O.'."""
    # As três fontes são independentes → busca em paralelo (antes era sequencial).
    async def _insights():
        if not knowledge_db:
            return {"enabled": False, "total": 0, "sampled": False,
                    "categories": [], "sectors": [], "domains": [], "recent": []}
        return {"enabled": True, **(await asyncio.to_thread(knowledge_db.insights))}

    async def _status():
        return await asyncio.to_thread(learner.get_status) if learner else {}

    async def _timeline():
        if not db:
            return []
        try:
            return await asyncio.to_thread(db.get_learning_timeline, 14)
        except Exception:
            return []

    base, ls, timeline = await asyncio.gather(_insights(), _status(), _timeline())
    base["learning"] = {
        "running": ls.get("running", False),
        "total_learned": ls.get("total_learned", 0),
        "learned_today": ls.get("learned_today", 0),
        "self_directed_count": ls.get("self_directed_count", 0),
        "throughput_hour": ls.get("throughput_hour", 0),
        "next_studies": ls.get("next_studies", []),
        "gap_count": ls.get("gap_count", 0),
        "recent_gaps": ls.get("recent_gaps", []),
        "agents": ls.get("agents", []),
    }
    base["timeline"] = timeline
    return base


@app.get("/api/models")
async def models_info():
    """Modelos disponíveis no provedor ativo (Ollama ou motor próprio) + qual o
    A.P.O.L.O. usa no chat. Orienta a baixar um modelo leve (3B) p/ respostas rápidas."""
    from src.providers import get_provider
    try:
        installed = await asyncio.to_thread(get_provider().list_models)
    except Exception as e:
        logger.warning(f"models list: {e}")
        installed = []
    chat_is_fast = CHAT_MODEL in FAST_MODELS
    return {
        "chat_model": CHAT_MODEL,
        "heavy_model": MODEL,
        "vision_model": VISION_MODEL,
        "has_vision": bool(VISION_MODEL),
        "installed": installed,
        "chat_is_fast": chat_is_fast,
        # Sugere um 3B só se o chat ainda não usa um modelo rápido.
        "suggestion": "" if chat_is_fast else "qwen2.5-coder:3b",
    }


# ── Rotas de aprendizado autônomo ────────────────────────────

class StudyRequest(BaseModel):
    topic: str


@app.post("/api/learning/start")
async def start_learning():
    await learner.start()
    return {"ok": True, "status": learner.get_status()}


@app.post("/api/learning/stop")
async def stop_learning():
    await learner.stop()
    return {"ok": True, "status": learner.get_status()}


@app.post("/api/learning/repair")
async def learning_repair(limit: int = 8):
    """Repara sínteses cruas (timeouts antigos salvaram texto truncado como
    conhecimento): re-sintetiza em background e avisa via notificação."""
    if not learner or not db:
        return {"ok": False, "error": "learner indisponível"}
    rows = await asyncio.to_thread(db.get_learning_history, 300)
    found = sum(1 for r in rows if learner._looks_raw(r.get("summary", "")))
    if not found:
        return {"ok": True, "found": 0}
    asyncio.create_task(learner.repair_raw_summaries(limit))
    return {"ok": True, "found": found, "started": min(found, limit)}


@app.get("/api/learning/status")
async def learning_status():
    return learner.get_status() if learner else {"running": False}


@app.get("/api/learning/stream")
async def learning_stream():
    """SSE push do status do aprendizado — substitui o polling de 3 s/3 s do frontend.
    O cliente conecta uma vez e recebe updates quando algo muda, sem polling."""
    async def _events():
        last_hash = None
        while True:
            try:
                st = learner.get_status() if learner else {"running": False}
                # Serializa e compara hash — só envia quando o estado mudou
                payload = json.dumps(st, sort_keys=True)
                h = hash(payload)
                if h != last_hash:
                    last_hash = h
                    yield f"data: {payload}\n\n"
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)
    return StreamingResponse(
        _events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/learning/study-now")
async def study_now(req: StudyRequest):
    """Estuda um tópico imediatamente, independente do modo estar ligado."""
    if not learner:
        return {"ok": False, "error": "Learner não inicializado"}
    result = await learner.study_now(req.topic)
    return result


@app.get("/api/learning/history")
async def learning_history(limit: int = 200):
    if not db:
        return []
    items = db.get_learning_history(limit=limit)
    from src.topics import classify_sector
    for it in items:
        it["sector"] = classify_sector(it.get("topic", ""))
    return items


@app.get("/api/learning/timeline")
async def learning_timeline(days: int = 14):
    if not db:
        return []
    return await asyncio.to_thread(db.get_learning_timeline, days)


@app.get("/api/digest")
async def digest(hours: int = 24):
    """Digest 'o que aprendi' — tópicos recentes agrupados por setor."""
    if not db:
        return {"hours": hours, "total": 0, "sectors": []}
    items = await asyncio.to_thread(db.get_learned_since, hours)
    from src.topics import classify_sector, SECTOR_LABELS
    by_sector: dict[str, list[str]] = {}
    for it in items:
        s = classify_sector(it.get("topic", ""))
        by_sector.setdefault(s, []).append(_clean_topic(it.get("topic", "")))
    sectors = sorted(
        ({"sector": s, "label": SECTOR_LABELS.get(s, s), "count": len(v), "samples": v[:5]}
         for s, v in by_sector.items()),
        key=lambda x: x["count"], reverse=True,
    )
    return {"hours": hours, "total": len(items), "sectors": sectors,
            "generated_at": datetime.now().isoformat()}


@app.get("/api/learning/agents")
async def learning_agents():
    """Status em tempo real de cada mini-agente."""
    if not learner:
        return []
    status = learner.get_status()
    return status.get("agents", [])


@app.get("/api/knowledge/search")
async def search_knowledge(q: str = ""):
    if not q or not knowledge_db:
        return []
    results = await asyncio.to_thread(knowledge_db.search, q, 5)
    return results


@app.get("/api/knowledge/recent")
async def knowledge_recent(limit: int = 10):
    """Últimos tópicos aprendidos com sumário."""
    if not db:
        return []
    return db.get_learning_history(limit=limit)


# PWA: service worker e manifest precisam ser servidos da raiz com headers corretos.
# O service worker em /sw.js tem escopo máximo (toda a app); se servido de /static/sw.js
# o escopo seria limitado a /static/, quebrando o cache das páginas do app.
@app.get("/sw.js")
async def pwa_sw():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0"},
    )

@app.get("/manifest.json")
async def pwa_manifest():
    return FileResponse(
        "static/manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/apolo-icon.svg")
async def pwa_icon_svg():
    return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")

@app.get("/apolo-icon-192.png")
async def pwa_icon_192():
    path = "static/apolo-icon-192.png"
    if not os.path.exists(path):
        return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")
    return FileResponse(path, media_type="image/png")

@app.get("/apolo-icon-512.png")
async def pwa_icon_512():
    path = "static/apolo-icon-512.png"
    if not os.path.exists(path):
        return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")
    return FileResponse(path, media_type="image/png")

app.mount("/", StaticFiles(directory="static", html=True), name="static")


# ── Execução direta: `python app.py` sobe o servidor ─────────
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    reload = os.getenv("APOLO_RELOAD", "1") not in ("0", "false", "False", "")

    print("=" * 56)
    print("  ☀️  A.P.O.L.O. iniciando...")
    print(f"  →  Abra no navegador: http://127.0.0.1:{port}")
    print("  →  Para parar: Ctrl+C")
    print("=" * 56)

    # Com reload=True o uvicorn precisa do import string, não do objeto app.
    uvicorn.run("app:app", host=host, port=port, reload=reload)
