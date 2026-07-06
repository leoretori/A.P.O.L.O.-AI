"""Chat principal do A.P.O.L.O. — o endpoint central e mais denso: recall
semântico (RAG) + base FTS em paralelo, auto-pesquisa na web em lacunas, system
prompt com cache por sessão, memória de conversa longa (resumo rolante), visão,
auto-upgrade para o 14b, self-eval, execução de código gerado e persistência.

Rota: /api/chat. Último endpoint extraído de app.py na M1 do JARVIS_ROADMAP —
com ele o app.py deixa de ter rotas próprias e vira só bootstrap + lifespan +
scheduler + middlewares. Lê todos os singletons via runtime e a infra comum via
chat_common; as constantes de tuning do chat moram aqui.
"""
import asyncio
import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src import runtime as rt
from src import chat_common as cc
from src.coder_state import gpu_priority
from src.llm import stream_chat, chat_resilient, KEEP_ALIVE, KEEP_ALIVE_HEAVY
from src.routing import is_complex
from src.utils import extract_code, extract_explanation, sanitize_request
from src.web_search import web_research
from src.episodic import index_session as _index_episodic
from src.system_cache import get as _syscache_get, put as _syscache_put
from src.query_cache import (
    recall_get as _qcache_recall_get, recall_put as _qcache_recall_put,
    fts_get as _qcache_fts_get, fts_put as _qcache_fts_put,
)
from src.prompts import (
    SYSTEM_PROMPT, GENERATE_PROMPT, PERSONAL_SECTION,
    MEMORY_SECTION, KNOWLEDGE_SECTION, WEB_SECTION, FACT_EXTRACT_PROMPT,
    CONVERSATION_SUMMARY_PROMPT, CONVERSATION_SUMMARY_SECTION, AGENT_SELFEVAL_PROMPT,
)

router = APIRouter()
logger = logging.getLogger("apolo.routers.chat")

# ── Tuning do chat (env) ──────────────────────────────────────────
MAX_HISTORY = int(os.getenv("MAX_HISTORY", 12))
SUMMARY_TRIGGER = int(os.getenv("SUMMARY_TRIGGER", 16))
SUMMARY_STALE = int(os.getenv("SUMMARY_STALE", 8))
KNOWLEDGE_TIMEOUT = float(os.getenv("KNOWLEDGE_TIMEOUT", 4))
AUTO_SMART = os.getenv("AUTO_SMART", "1") not in ("0", "false", "False", "")
MEMORY_RECALL_N = int(os.getenv("MEMORY_RECALL_N", 6))
MEMORY_TOP = int(os.getenv("MEMORY_TOP", 3))
MEMORY_MIN_RELEVANCE = float(os.getenv("MEMORY_MIN_RELEVANCE", 0.18))
MEMORY_SNIPPET = int(os.getenv("MEMORY_SNIPPET", 400))
AUTO_WEB_ON_GAP = os.getenv("AUTO_WEB_ON_GAP", "1") not in ("0", "false", "False")
# Contexto rico: nº de memórias relevantes que já justifica subir para o 14b.
MEMORY_RICH_14B = int(os.getenv("MEMORY_RICH_14B", 2))
# Self-eval no chat (só no 14b, respostas longas de texto). CHAT_SELF_EVAL=0 desativa.
CHAT_SELF_EVAL = os.getenv("CHAT_SELF_EVAL", "1") not in ("0", "false", "False")
# Mensagens curtas (sim/ok/continue): fast path sem recall/FTS.
SHORT_MSG_CHARS = int(os.getenv("SHORT_MSG_CHARS", 40))

# Pistas de que a mensagem fala do usuário — só aí vale a pena rodar a extração de fato.
_FACT_CUES = (
    "meu ", "minha ", "eu ", " sou ", "estou ", "trabalho", "uso ", "utilizo",
    "prefiro", "gosto", "projeto", "stack", "nosso", "nossa", "to usando", "tô usando",
)


async def _maybe_extract_fact(message: str) -> None:
    """Aprende um fato pessoal a partir da mensagem (background, não bloqueia o chat).
    Só roda quando a mensagem tem cara de pessoal, p/ evitar ruído e custo de LLM."""
    if not rt.profile:
        return
    low = message.lower()
    if not any(cue in low for cue in _FACT_CUES):
        return
    try:
        prompt = FACT_EXTRACT_PROMPT.format(message=message[:400])
        fact = await asyncio.to_thread(
            chat_resilient,
            rt.get_chat_model(),
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE,
            options={"num_predict": 40},
        )
        fact = (fact or "").strip().strip('"').strip()
        if fact and "NONE" not in fact.upper() and len(fact) > 5:
            added = rt.profile.add(fact, source="auto")
            if added:
                logger.info(f"[profile] fato auto-aprendido: {fact[:60]}")
    except Exception as e:
        logger.debug(f"fact extract: {e}")


async def _update_session_summary(session_id: str) -> None:
    """Resume as mensagens antigas de uma conversa longa (background, não bloqueia).
    A próxima resposta passa a contar com o resumo no system prompt."""
    hist = rt.sessions.get(session_id, [])
    older = hist[:-MAX_HISTORY] if len(hist) > MAX_HISTORY else []
    if len(hist) <= SUMMARY_TRIGGER or not older:
        return
    convo = "\n".join(f"{m['role']}: {(m.get('content') or '')[:500]}" for m in older[-40:])
    try:
        prompt = CONVERSATION_SUMMARY_PROMPT.format(conversation=convo)
        text = await asyncio.to_thread(
            chat_resilient, rt.get_chat_model(),
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE, options={"num_predict": 240},
        )
        text = (text or "").strip()
        if text:
            rt.session_summaries[session_id] = {"text": text[:1500], "upto": len(older)}
            logger.info(f"[summary] sessão {session_id[:8]} resumida ({len(older)} msgs)")
            # Indexa a conversa no RAG para recall semântico em sessões futuras.
            if rt.rag:
                title = rt.db.list_sessions(0, 200)
                title = next((s.get("title", "") for s in title if s["session_id"] == session_id), "")
                all_msgs = rt.sessions.get(session_id, [])
                await asyncio.to_thread(_index_episodic, session_id, title, all_msgs, rt.rag, text)
    except Exception as e:
        logger.debug(f"summary: {e}")


@router.post("/api/chat")
async def chat(req: cc.ChatRequest):
    cc.mark_request()
    request = sanitize_request(req.message)
    history = cc.get_session(req.session_id)

    # Adiciona pergunta ao learner para estudo aprofundado
    if rt.learner:
        rt.learner.add_user_topic(request)

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
                    if rt.knowledge_db and web_context:
                        asyncio.create_task(asyncio.to_thread(
                            rt.knowledge_db.save,
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
        async def _do_recall() -> list[dict]:
            if not rt.rag or _is_short:
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
                recalled = await asyncio.to_thread(rt.rag.recall, enriched, MEMORY_RECALL_N)
                result = [
                    m for m in recalled if (m.get("relevance") or 0) >= MEMORY_MIN_RELEVANCE
                ][:MEMORY_TOP]
                return _qcache_recall_put(enriched, result)
            except Exception as e:
                logger.debug(f"recall: {e}")
                return []

        async def _do_fts() -> str:
            if not rt.knowledge_db or _is_short:
                return ""
            # #2 Cache: FTS do mesmo query → resultado imediato
            cached = _qcache_fts_get(request)
            if cached is not None:
                return cached
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(rt.knowledge_db.format_context, request),
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
        if is_gap and rt.learner:
            rt.learner.note_gap(request)
            try:
                rt.db.add_notification(f"🔍 Lacuna detectada — vou estudar: {request[:80]}", kind="gap")
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
                        if rt.knowledge_db and web_context:
                            asyncio.create_task(asyncio.to_thread(
                                rt.knowledge_db.save,
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
        profile_facts = rt.profile.as_context() if rt.profile else ""
        proj_section  = rt.project_mem.as_prompt_section() if rt.project_mem else ""

        system_content = _syscache_get(req.session_id, profile_facts, proj_section)
        if system_content is None:
            system_content = SYSTEM_PROMPT
            if profile_facts:
                system_content += PERSONAL_SECTION.format(facts=profile_facts)
            if proj_section:
                system_content += proj_section
            _syscache_put(req.session_id, system_content, profile_facts, proj_section)

        # Memória de conversa longa: injeta o resumo das mensagens antigas (não enviadas).
        summ = rt.session_summaries.get(req.session_id)
        if summ and len(history) > SUMMARY_TRIGGER and summ.get("text"):
            system_content += CONVERSATION_SUMMARY_SECTION.format(summary=summ["text"])

        messages = [{"role": "system", "content": system_content}]
        messages.extend(history[-MAX_HISTORY:])
        user_msg = {"role": "user", "content": user_content}

        # ── Visão: se há imagem, anexa-a e usa um modelo de visão local ──
        vision_model = rt.get_vision_model()
        has_image = bool(req.image)
        if has_image and not vision_model:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Para eu analisar imagens, baixe um modelo de visão: ollama pull llava'})}\n\n"
            return
        if has_image:
            user_msg["images"] = [req.image]
        messages.append(user_msg)

        # Seleção de modelo: visão > inteligente (14b) > leve (chat do dia a dia).
        heavy_model = rt.model
        chat_model = rt.get_chat_model()
        rich_context = len(memories) >= MEMORY_RICH_14B
        auto_smart = AUTO_SMART and not req.smart and not has_image and (
            is_complex(request) or rich_context
        )
        smart = (req.smart or auto_smart) and heavy_model != chat_model
        if has_image:
            active_model, keep = vision_model, KEEP_ALIVE_HEAVY
            yield f"data: {json.dumps({'type': 'status', 'message': f'👁️ Analisando a imagem com {vision_model}...'})}\n\n"
        elif smart:
            active_model, keep = heavy_model, KEEP_ALIVE_HEAVY
            if rich_context and not is_complex(request):
                why = f"contexto rico ({len(memories)} memórias) — síntese profunda"
            else:
                why = "pergunta complexa detectada" if auto_smart else "modo inteligente"
            yield f"data: {json.dumps({'type': 'status', 'message': f'{why} — usando {heavy_model}...'})}\n\n"
        else:
            active_model, keep = chat_model, KEEP_ALIVE

        # ── Fase 5: Streaming do LLM (em thread — não bloqueia o event loop) ──
        full_response = ""
        try:
            async for token in stream_chat(active_model, messages, keep_alive=keep):
                full_response += token
                yield f"data: {json.dumps({'type': 'token', 'content': token})}\n\n"

            # #6 Self-eval no chat: só quando usando 14b e resposta longa de texto.
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
            is_first_message = len(rt.sessions[req.session_id]) == 0
            rt.sessions[req.session_id].append({"role": "user", "content": request})
            rt.sessions[req.session_id].append({"role": "assistant", "content": full_response})
            rt.db.save_message(req.session_id, "user", request)
            rt.db.save_message(req.session_id, "assistant", full_response)

            # #10 Trim de sessão: evita crescimento ilimitado de RAM.
            _sess = rt.sessions[req.session_id]
            _keep = 2 * MAX_HISTORY + 4
            if len(_sess) > _keep:
                rt.sessions[req.session_id] = _sess[-_keep:]

            # Gera título da sessão na primeira mensagem (em background)
            if is_first_message:
                asyncio.create_task(cc.generate_session_title(req.session_id, request))

            # Aprende um fato pessoal sobre o usuário, se houver (background, não bloqueia)
            asyncio.create_task(_maybe_extract_fact(request))

            # Conversa longa: atualiza o resumo rolante (background) quando ficar defasado.
            hist_now = rt.sessions[req.session_id]
            if len(hist_now) > SUMMARY_TRIGGER:
                s = rt.session_summaries.get(req.session_id)
                if not s or (len(hist_now) - s.get("upto", 0)) > SUMMARY_STALE:
                    asyncio.create_task(_update_session_summary(req.session_id))

            code = extract_code(full_response)
            explanation = extract_explanation(full_response)
            has_code = "```" in full_response

            exec_result = None
            if has_code and code:
                exec_result = rt.executor.run(code)
                if exec_result.success and rt.rag:
                    rt.rag.add_example(
                        content=f"# Pedido: {request}\n\n{code}",
                        doc_id=f"gerado_{hash(request) & 0xFFFFFF}",
                    )

            rt.db.save_execution({
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
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
