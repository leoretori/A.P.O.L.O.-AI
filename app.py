"""A.P.O.L.O. — Agente Pessoal de Operações, Lógica e Otimização."""

import asyncio
import os
import sys
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware   # #3
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

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
    KEEP_ALIVE, warmup,
)
from src.coder import CoderWorkspace
from src.lessons import LessonMemory
from src.project_memory import ProjectMemory
from src.memory import MemoryFabric, EpisodicMemory
from src.model_select import pick_chat_model, pick_vision_model
from src.routing import is_complex
from src import runtime as rt
from routers.assets import router as assets_router
from routers.learning import router as learning_router
from routers.sessions import router as sessions_router
from routers.profile import router as profile_router
from routers.schedules import router as schedules_router
from routers.notifications import router as notifications_router
from routers.knowledge import router as knowledge_router
from routers.analytics import router as analytics_router
from routers.ingest import router as ingest_router
from routers.voice import router as voice_router
from routers.backup import router as backup_router
from routers.project import router as project_router
from routers.system import router as system_router
from routers.coder_tools import router as coder_tools_router
from routers.coder_write import router as coder_write_router
from routers.coder_ops import router as coder_ops_router
from routers.coder_run import router as coder_run_router
from routers.health import router as health_router
from routers.ai import router as ai_router
from routers.agent import router as agent_router
from routers.coder import router as coder_router
from routers.chat import router as chat_router
from routers.tools import router as tools_router
from routers.wake import router as wake_router
from routers.verify import router as verify_router
from routers.evals import router as evals_router
from routers.actions import router as actions_router
from routers.routines import router as routines_router
from routers.webtask import router as webtask_router
from routers.remote import router as remote_router
from routers.embeddings import router as embeddings_router
from routers.projects import router as projects_router
from routers.retrospective import router as retrospective_router
from routers.nano import router as nano_router
from routers.memory import router as memory_router
from routers.vision import router as vision_router
import src.tools  # noqa: F401 — registra as ferramentas de agência no import (M6)

# Windows: o console cp1252 não encoda emoji (☀️, 🎯, ✓...) e quebra prints/logs.
# Força UTF-8 nos streams para o A.P.O.L.O. rodar em qualquer terminal.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# #4 Logging otimizado: app fica em INFO, libs barulhentas em WARNING.
# httpx/httpcore geram 1 log por requisição de rede — em produção são dezenas/min.
# LOG_LEVEL=DEBUG restaura tudo para debug; LOG_FORMAT=json liga logs estruturados.
from src.logging_setup import configure_logging
_LOG_FORMAT = configure_logging()
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
# Tuning do chat (MAX_HISTORY, recall semântico, self-eval, auto-web etc.) mora
# em routers/chat.py; app.py mantém só o que o bootstrap/lifespan/scheduler usa.
LEARNING_INTERVAL = int(os.getenv("LEARNING_INTERVAL", 180))
# Rate limiting: máximo de requisições por endpoint por janela de 60s.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT", "1") not in ("0", "false", "False")
_rate_windows: dict[str, list] = defaultdict(list)
_RATE_LIMITS = {"/api/chat": 40, "/api/research": 15, "/api/agent": 20,
                "/api/orchestrate": 10, "default": 80}
# Idle learning: se o usuário ficar inativo por IDLE_TRIGGER segundos e o
# aprendizado estiver parado, o A.P.O.L.O. o inicia automaticamente.
# 0 = desativado. Padrão 600 (10 min). GpuGate já preempta o learner quando
# o usuário mandar uma mensagem — não há conflito.
IDLE_TRIGGER = int(os.getenv("IDLE_TRIGGER", 600))
# API LAN: token de acesso para expor a API na rede local (vazio = sem autenticação).
API_TOKEN = os.getenv("API_TOKEN", "").strip()
# Acesso remoto seguro (M11 11.3): se REMOTE_TOKEN estiver definido, todo acesso de
# fora da máquina (não-loopback) exige o token — cobre a UI inteira via cookie. O
# dono, no localhost, continua livre. Sem ele, comportamento inalterado.
REMOTE_TOKEN = os.getenv("REMOTE_TOKEN", "").strip()
# Briefing diário (M4 4.1): hora local (0–23) a partir da qual o A.P.O.L.O. te
# aborda com o resumo do dia, uma vez por dia. -1 desliga.
BRIEFING_HOUR = int(os.getenv("BRIEFING_HOUR", 8))
_last_briefing_date = None

# Backup cifrado automático (M11 11.2): se BACKUP_PASSPHRASE estiver no .env, o
# A.P.O.L.O. grava 1 backup local cifrado por dia a partir de BACKUP_HOUR.
BACKUP_HOUR = int(os.getenv("BACKUP_HOUR", 3))
_last_backup_date = None

# Flywheel noturno do Nano (M25.3): 1x/dia a partir de FLYWHEEL_HOUR, se houver
# checkpoint do Nano, o Qwen destila as conversas reais → treina um candidato →
# promove SÓ se medir melhora. Pesado (CPU); só roda ocioso e com o learner
# parado. -1 desliga (padrão: 3h da manhã). O treino roda em thread p/ não travar.
FLYWHEEL_HOUR = int(os.getenv("FLYWHEEL_HOUR", 3))
FLYWHEEL_STEPS = int(os.getenv("FLYWHEEL_STEPS", 400))
_last_flywheel_date = None

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
# ChatRequest, o título de sessão e a marca de atividade do usuário ficam em
# src/chat_common.py (compartilhados com os routers de IA). Aliases mantêm os
# usos deste módulo intactos.
from src.chat_common import (
    last_request_at as _last_request_at_fn,
)


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
    global CHAT_MODEL
    await asyncio.sleep(20)  # deixa o startup assentar
    tick = 0
    while True:
        tick += 1
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

            # Rotinas automatizadas (M10 10.2): tarefas recorrentes que o A.P.O.L.O.
            # executa sozinho (ex.: "toda sexta, resumo da semana"). Cada execução
            # passa pelo motor de ações → auditada e reversível (ledger de undo). Os
            # builders são determinísticos (não usam o LLM) → não disputam o Ollama.
            try:
                from src import routines as _routines
                _all = await asyncio.to_thread(db.list_routines, True)
                for r in _routines.due_routines(_all, datetime.now()):
                    db.mark_routine_run(r["id"], datetime.now())   # marca antes p/ não repetir
                    res = await asyncio.to_thread(_routines.run_routine, r, db)
                    if res.get("ok"):
                        db.add_notification(f"🛠️ Rotina: {res.get('description', r['name'])}",
                                            kind="info", link="")
                        logger.info(f"[rotina] executada: {r['name']} → {res.get('description')}")
                    else:
                        db.add_notification(
                            f"⚠️ Rotina '{r['name']}' não rodou: {res.get('error', 'erro')[:120]}",
                            kind="info")
                        logger.warning(f"[rotina] {r['name']} falhou: {res.get('error')}")
            except Exception as e:
                # warning (não debug): um bug de código aqui (NameError/AttributeError)
                # já ficou invisível uma vez — "buscados:0" por meses, sem sinal visível,
                # porque o debug não aparece nos logs padrão (INFO). Ver lição na memória.
                logger.warning(f"[rotina] loop: {e}")

            # Backup cifrado automático (M11 11.2): 1x/dia a partir de BACKUP_HOUR,
            # se houver senha no .env. Nada em texto puro; poda os antigos.
            global _last_backup_date
            _bp = os.getenv("BACKUP_PASSPHRASE", "").strip()
            if _bp:
                _tb = datetime.now()
                if _tb.hour >= BACKUP_HOUR and _last_backup_date != _tb.date():
                    _last_backup_date = _tb.date()
                    try:
                        from routers.backup import _gather_backup_data
                        from src import backup_service
                        _data = await asyncio.to_thread(_gather_backup_data)
                        _info = await asyncio.to_thread(backup_service.write_encrypted, _data, _bp)
                        await asyncio.to_thread(backup_service.prune_backups)
                        logger.info(f"[backup] backup cifrado diário: {_info['name']} ({_info['bytes']} bytes)")
                    except Exception as e:
                        logger.warning(f"[backup] auto falhou: {e}")

            # Idle learning: ativa o aprendizado autônomo quando a máquina está ociosa.
            if IDLE_TRIGGER > 0 and learner and not learner.running:
                _lra = _last_request_at_fn()
                idle = _time.perf_counter() - _lra if _lra > 0 else 0
                if idle > IDLE_TRIGGER:
                    logger.info(f"[idle] {idle:.0f}s sem requisição → iniciando aprendizado autônomo")
                    await learner.start()

            # Auto-recuperação do modelo leve: se o app subiu com o Ollama fora
            # do ar, CHAT_MODEL caiu no 14b (fallback) e a sumarização leve não
            # engatou. Quando o Ollama volta, re-escolhemos o modelo leve sem
            # precisar reiniciar o app. Tenta a cada 5 min (não polui o log).
            if CHAT_MODEL == MODEL and tick % 5 == 0:
                picked = await asyncio.to_thread(_pick_chat_model)
                if picked != MODEL:
                    CHAT_MODEL = picked
                    if learner and not os.getenv("SUMMARIZE_MODEL", "").strip():
                        learner.summarize_model = CHAT_MODEL
                    logger.info(f"[recover] Ollama voltou — modelo leve re-selecionado: {CHAT_MODEL}")
                    db.add_notification(
                        f"✅ Ollama voltou — chat e sumarização no modelo leve ({CHAT_MODEL})",
                        kind="info")

            # Consolidação de memória ("sono", Épico 2.3): a cada ~30 min, resume
            # conversas já encerradas em episódios datados — o gatilho automático
            # que faltava. Evita rodar enquanto o aprendizado de fundo usa o LLM
            # (ambos disputam o Ollama leve); o GpuGate ainda prioriza o usuário.
            if rt.episodic and tick % 30 == 0 and not (learner and learner.running):
                res = await asyncio.to_thread(rt.episodic.consolidate)
                if res.get("consolidated"):
                    logger.info(f"[sono] {res['consolidated']} conversa(s) viraram memória de longo prazo")

            # Follow-ups (M4 4.2): resurface lembretes vencidos como notificação.
            try:
                for rem in await asyncio.to_thread(db.due_reminders):
                    db.add_notification(f"⏰ Lembrete: {rem['text'][:120]}", kind="reminder")
                    db.mark_reminder_notified(rem["id"])
                    logger.info(f"[reminder] vencido → avisado: {rem['text'][:60]}")
            except Exception as e:
                logger.warning(f"[reminder] resurface: {e}")

            # Briefing diário (M4 4.1): a partir de BRIEFING_HOUR, uma vez por dia,
            # o A.P.O.L.O. te aborda primeiro com o resumo do dia (vira notificação;
            # o front pode falá-lo). Guarda a data p/ não repetir.
            global _last_briefing_date
            if BRIEFING_HOUR >= 0:
                _today = datetime.now()
                if _today.hour >= BRIEFING_HOUR and _last_briefing_date != _today.date():
                    _last_briefing_date = _today.date()
                    try:
                        from src.briefing import build_briefing
                        b = await asyncio.to_thread(build_briefing, db, rt.episodic,
                                                    learner, profile, 12)
                        db.add_notification(f"☀️ {b['text'][:400]}", kind="briefing")
                        logger.info("[briefing] briefing diário enviado")
                    except Exception as e:
                        logger.warning(f"[briefing] {e}")

            # Flywheel noturno do Nano (M25.3): 1x/dia a partir de FLYWHEEL_HOUR,
            # o Qwen destila as conversas reais e o Nano treina um candidato —
            # promovido SÓ se medir melhora (portão de qualidade, reversível). É
            # pesado (treino NumPy no CPU): só quando ocioso e com o learner
            # parado, para não disputar recurso com o usuário nem com o estudo.
            global _last_flywheel_date
            if FLYWHEEL_HOUR >= 0 and not (learner and learner.running):
                _tf = datetime.now()
                _idle_ok = True
                if IDLE_TRIGGER > 0:
                    _lr = _last_request_at_fn()
                    _idle_ok = (_time.perf_counter() - _lr) > IDLE_TRIGGER if _lr > 0 else True
                if (_tf.hour >= FLYWHEEL_HOUR and _last_flywheel_date != _tf.date()
                        and _idle_ok):
                    from src.nanollm.engine import NanoEngine
                    if NanoEngine().available():
                        _last_flywheel_date = _tf.date()  # marca antes p/ não repetir
                        try:
                            from src.nanollm.flywheel import run_nightly_flywheel
                            logger.info("[flywheel] iniciando ciclo noturno do Nano…")
                            res = await asyncio.to_thread(
                                run_nightly_flywheel, db, steps=FLYWHEEL_STEPS)
                            st = res.get("status")
                            if st == "promoted":
                                if rt.nano:            # serve o cérebro novo já
                                    rt.nano.reload()
                                db.add_notification(
                                    f"🌀 Nano evoluiu de madrugada: perplexidade "
                                    f"{res['incumbent_val']:.2f} → {res['candidate_val']:.2f} "
                                    f"(ganho {res.get('gain')}, {res.get('pairs')} pares). "
                                    f"Já estou servindo o novo cérebro.", kind="info")
                                logger.info(f"[flywheel] promovido: {res}")
                            elif st == "rejected":
                                logger.info(f"[flywheel] candidato rejeitado: {res.get('reason')}")
                            else:
                                logger.info(f"[flywheel] pulado: {res.get('reason')}")
                        except Exception as e:
                            logger.warning(f"[flywheel] ciclo falhou: {e}")
        except Exception as e:
            # warning (não debug): esta é a rede de segurança de TODA a tick do
            # scheduler (agenda/rotinas/backup/idle/sono/lembretes/briefing/flywheel).
            # Um bug de código em qualquer parte cairia aqui e, em debug, ficaria
            # invisível para sempre (o log do usuário roda em INFO) - foi exatamente
            # o "buscados:0" que passou meses sem sinal. Ver lição na memória.
            logger.warning(f"[scheduler] loop: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, rag, executor, learner, researcher, reviewer, ingestor, curator, profile, gpu_gate, coder_ws, project_mem, lesson_mem, CHAT_MODEL, VISION_MODEL, MODEL

    # Motor próprio (llama.cpp): divide os GGUFs de LLAMACPP_MODELS em papéis —
    # chat do dia a dia no MENOR (rápido na CPU), 'Inteligente'/pesado no MAIOR.
    # Resolvido ANTES do rt.init (que fixa rt.model). Sem isto o chat caía no
    # modelo grande e cada resposta demorava. Overrides: LLAMACPP_CHAT_MODEL /
    # LLAMACPP_HEAVY_MODEL. Com 1 só modelo, nada muda.
    _llc_roles = False
    if os.getenv("LLM_BACKEND", "ollama").strip().lower() == "llamacpp":
        from src.model_select import pick_llamacpp_roles
        from src.providers import LlamaCppProvider
        _mm = LlamaCppProvider._parse_model_map(os.getenv("LLAMACPP_MODELS", ""))
        _chat, _heavy = pick_llamacpp_roles(
            _mm, os.getenv("LLAMACPP_CHAT_MODEL", "").strip(),
            os.getenv("LLAMACPP_HEAVY_MODEL", "").strip())
        if _chat and _heavy and _chat != _heavy:
            MODEL, CHAT_MODEL, _llc_roles = _heavy, _chat, True
            logger.info(f"[llamacpp] chat leve: {_chat} · pesado (Inteligente): {_heavy}")

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
    # Publica os singletons para os routers modularizados (M1). Enquanto a migração
    # não termina, eles continuam como globais aqui — mesma referência de objeto.
    # Tecido de memória unificado (M2): uma porta só sobre RAG + base + lições +
    # memória episódica/autobiográfica (conversas datadas, recall temporal).
    episodic = EpisodicMemory(db=db)
    memory = MemoryFabric(rag=rag, knowledge=knowledge_db, lessons=lesson_mem,
                          episodic=episodic)
    # Apolo-Nano (LLM própria, src/nanollm): engine leve — pesos carregam lazy
    # na 1ª completion; sem checkpoint, /api/nano responde available=False.
    from src.nanollm.engine import NanoEngine
    nano = NanoEngine()
    rt.configure(learner=learner, db=db, knowledge_db=knowledge_db, rag=rag,
                 sessions=sessions, session_summaries=session_summaries,
                 profile=profile, curator=curator, ingestor=ingestor,
                 project_mem=project_mem, coder_ws=coder_ws, model=MODEL,
                 lesson_mem=lesson_mem, gpu_gate=gpu_gate, nano=nano,
                 reviewer=reviewer, researcher=researcher, executor=executor,
                 memory=memory, episodic=episodic,
                 get_chat_model=lambda: CHAT_MODEL,
                 get_vision_model=lambda: VISION_MODEL)
    # Limpa títulos órfãos (sessões cujas mensagens já foram apagadas).
    try:
        orphans = db.cleanup_orphan_meta()
        if orphans:
            logger.info(f"Sessões fantasmas removidas: {orphans}")
    except Exception as e:
        logger.debug(f"cleanup_orphan_meta: {e}")
    # Resolve o modelo leve do chat (rápido na CPU); o maior fica p/ tarefas pesadas.
    # No motor próprio os papéis já vieram de LLAMACPP_MODELS (acima) — não sobrescreve.
    if not _llc_roles:
        CHAT_MODEL = _pick_chat_model()
    VISION_MODEL = _pick_vision_model()
    # Sumarização do aprendizado no modelo LEVE por padrão: com o 14b na CPU cada
    # síntese estourava o timeout de 120s (TODO item era salvo como conteúdo cru,
    # e a geração órfã seguia ocupando o Ollama, atrasando os próximos em cascata).
    # SUMMARIZE_MODEL definido no .env continua mandando.
    if not os.getenv("SUMMARIZE_MODEL", "").strip() and learner and CHAT_MODEL != MODEL:
        learner.summarize_model = CHAT_MODEL
        logger.info(f"[learner] sumarização no modelo leve: {CHAT_MODEL}")
    # Pré-carrega o modelo LEVE (chat + sumarização do learner) — é o caminho comum.
    asyncio.create_task(warmup(CHAT_MODEL))
    # O modelo PESADO NÃO é pré-carregado por padrão: em CPU com pouca RAM (ex.: 16GB),
    # manter o 7B + o 1.5B residentes ao mesmo tempo pressiona a memória → swap → a
    # síntese do learner no 1.5B fica lenta e ESTOURA o timeout de 120s (o estudo
    # parava de salvar). O pesado carrega sob demanda no 1º uso do Inteligente/Profundo.
    # WARMUP_HEAVY=1 restaura o pré-carregamento (para máquinas com RAM de sobra).
    if MODEL != CHAT_MODEL and os.getenv("WARMUP_HEAVY", "0") not in ("0", "false", "False", ""):
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

    # STT sempre pronto (M3 3.2): pré-carrega o Whisper para a 1ª ditada não pagar
    # o cold-start de carregar o modelo (segundos no CPU). Atrasa 12s p/ não
    # competir com o warmup do LLM. Desligar com STT_WARMUP=0.
    async def _warmup_stt():
        await asyncio.sleep(12)
        from src.whisper_stt import warmup as _stt_warmup, is_available as _stt_ok
        if _stt_ok() and os.getenv("STT_WARMUP", "1") != "0":
            ok = await asyncio.to_thread(_stt_warmup, os.getenv("WHISPER_MODEL", "base"))
            if ok:
                logger.info("[stt] Whisper pré-carregado — ditado sem cold-start")
    asyncio.create_task(_warmup_stt())

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
    from src.build_info import APP_VERSION, git_sha
    logger.info(
        f"A.P.O.L.O. pronto — v{APP_VERSION} ({git_sha()}) — modelo: {MODEL}{cm}{sm}{vm} "
        f"— keep_alive={KEEP_ALIVE} — logs={_LOG_FORMAT} "
        f"— 7 agentes + auto-currículo + pesquisa profunda + code review + visão",
        extra={"event": "boot", "version": APP_VERSION, "git_sha": git_sha()},
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


@app.middleware("http")
async def _asset_revalidation_middleware(request: Request, call_next):
    """Força revalidação do JS/CSS do próprio app. O StaticFiles manda ETag mas
    NÃO manda Cache-Control, então o navegador aplica cache heurístico e serve
    código VELHO sem revalidar depois de um update (problema que apareceu quando
    o JS saiu inline → arquivos externos no Épico 1.2). `no-cache` permite cachear
    mas obriga a checar o ETag a cada carga — barato (servidor local, resposta 304
    quando nada mudou) e garante que a UI nova chegue no usuário."""
    response = await call_next(request)
    path = request.url.path
    # Não sobrescreve políticas já definidas (ex.: /sw.js manda `no-store` no
    # router de assets — o service worker NUNCA pode ser cacheado).
    if ((path.endswith(".js") or path.endswith(".css"))
            and "cache-control" not in response.headers):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def _remote_gate_middleware(request: Request, call_next):
    """Acesso remoto seguro (M11 11.3). Registrado por ÚLTIMO → roda por PRIMEIRO
    (outermost): bloqueia antes de qualquer processamento. Só age se REMOTE_TOKEN
    estiver definido; o dono (loopback) passa sempre. Clientes de fora precisam do
    token (query `?token=`, header `X-Apolo-Token` ou cookie) — e o primeiro acesso
    por link com `?token=` ganha o cookie, então o celular não repete o token."""
    if not REMOTE_TOKEN:
        return await call_next(request)
    from src import remote_access
    q_token = request.query_params.get("token", "")
    provided = q_token or request.headers.get("X-Apolo-Token", "") or request.cookies.get(remote_access.COOKIE_NAME, "")
    client_host = request.client.host if request.client else ""
    decision = remote_access.authorize(client_host, REMOTE_TOKEN, provided)
    if not decision["allowed"]:
        return JSONResponse(
            {"error": "acesso remoto requer token", "hint": "abra o link com ?token=… fornecido pelo dono"},
            status_code=401)
    response = await call_next(request)
    # Primeiro acesso via link com token → fixa o cookie (sessão de 30 dias).
    if q_token and decision["reason"] == "token":
        response.set_cookie(remote_access.COOKIE_NAME, q_token, max_age=30 * 86400,
                            httponly=True, samesite="lax")
    return response


# PWA: service worker, manifest e ícones (routers/assets.py). Precisam vir da RAIZ
# com headers corretos e ANTES do mount de /static — senão o mount "/" captura tudo.
# Primeiro router extraído do monólito (M1 do JARVIS_ROADMAP).
app.include_router(assets_router)
app.include_router(learning_router)
app.include_router(sessions_router)
app.include_router(profile_router)
app.include_router(schedules_router)
app.include_router(notifications_router)
app.include_router(knowledge_router)
app.include_router(analytics_router)
app.include_router(ingest_router)
app.include_router(voice_router)
app.include_router(backup_router)
app.include_router(project_router)
app.include_router(system_router)
app.include_router(coder_tools_router)
app.include_router(coder_write_router)
app.include_router(coder_ops_router)
app.include_router(coder_run_router)
app.include_router(health_router)
app.include_router(ai_router)
app.include_router(agent_router)
app.include_router(coder_router)
app.include_router(chat_router)
app.include_router(tools_router)
app.include_router(wake_router)
app.include_router(verify_router)
app.include_router(evals_router)
app.include_router(actions_router)
app.include_router(routines_router)
app.include_router(webtask_router)
app.include_router(remote_router)
app.include_router(embeddings_router)
app.include_router(projects_router)
app.include_router(retrospective_router)
app.include_router(nano_router)
app.include_router(memory_router)
app.include_router(vision_router)

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
