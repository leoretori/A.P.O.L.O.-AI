"""Modo Agente (ReAct-lite) — o A.P.O.L.O. escreve código Python, EXECUTA de
verdade e usa o resultado real para responder; também busca na web e consulta a
própria base. Resposta com autocrítica (1 passe) e persistência da conversa.

Rota: /api/agent. Extraído de app.py na M1 do JARVIS_ROADMAP. Lê os singletons
via runtime (executor, rag, learner, profile, db, sessions) e a infra comum via
chat_common (ChatRequest, get_session, agent_recall, mark_request, título).
"""
import asyncio
import json
import logging
import os
import re

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src import runtime as rt
from src import chat_common as cc
from src.coder_state import gpu_priority
from src.llm import chat_resilient, KEEP_ALIVE
from src.utils import extract_code, sanitize_request
from src.web_search import web_research
from src.prompts import (
    SYSTEM_PROMPT, PERSONAL_SECTION, FIX_PROMPT,
    AGENT_INSTRUCTION, AGENT_MEMORY_SECTION, AGENT_SELFEVAL_PROMPT,
)

router = APIRouter()
logger = logging.getLogger("apolo.routers.agent")

MAX_HISTORY = int(os.getenv("MAX_HISTORY", 12))
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", 5))
MAX_AGENT_FIXES = int(os.getenv("MAX_AGENT_FIXES", 2))
AGENT_SELF_EVAL = os.getenv("AGENT_SELF_EVAL", "1") not in ("0", "false", "False", "")


def parse_agent_action(content: str) -> tuple[str, str]:
    """Decide a ação do agente a partir da resposta do modelo (ReAct).
    Retorna (tipo, payload): 'code' | 'web' | 'base' | 'final'."""
    code = extract_code(content)
    if code and "```" in content:
        return "code", code
    for line in content.splitlines():
        m = re.match(r"\s*BUSCAR_WEB:\s*(.+)", line, re.IGNORECASE)
        if m and len(m.group(1).strip()) >= 3:
            return "web", m.group(1).strip()
        m = re.match(r"\s*CONSULTAR_BASE:\s*(.+)", line, re.IGNORECASE)
        if m and len(m.group(1).strip()) >= 3:
            return "base", m.group(1).strip()
    return "final", content


def clean_agent_answer(text: str) -> str:
    """Remove vazamentos de scaffolding que modelos leves às vezes ecoam
    (ex.: 'RESPOSTA FINAL:', 'RESPOSTAR:', 'APENAS com a versão...')."""
    t = (text or "").strip()
    # Tolera markdown/pontuação antes do rótulo (ex.: '**RESPOSTA FINAL:**', '### RESPOSTA:').
    lead = r"^[\s*#>_`-]*"
    t = re.sub(lead + r"(RESPOSTA\s*FINAL|RESPOSTAR?|RESPOSTA)\s*:?[\s*]*", "", t, flags=re.IGNORECASE)
    t = re.sub(lead + r"APENAS com a vers[ãa]o[^\n:]*:?[\s*]*", "", t, flags=re.IGNORECASE)
    # Corta uma eventual cauda em que o modelo recomeça a ecoar o prompt de avaliação.
    t = re.split(r"\n\s*Avalie\s*:", t, maxsplit=1, flags=re.IGNORECASE)[0]
    return t.strip()


@router.post("/api/agent")
async def agent(req: cc.ChatRequest):
    """Modo Agente (ReAct-lite): o A.P.O.L.O. escreve código Python, EXECUTA de
    verdade e usa o resultado real para responder — cálculos/lógica ficam exatos."""
    cc.mark_request()
    question = sanitize_request(req.message)
    if rt.learner:
        rt.learner.add_user_topic(question)
    history = cc.get_session(req.session_id)
    model = rt.get_chat_model()  # qwen2.5-coder escreve código muito bem mesmo no leve

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        answer = ""
        try:
            system_content = SYSTEM_PROMPT + AGENT_INSTRUCTION
            if rt.profile:
                facts = rt.profile.as_context()
                if facts:
                    system_content += PERSONAL_SECTION.format(facts=facts)

            # ── (2) Memória de longo prazo: recupera soluções/conhecimento já produzidos ──
            yield _ev({"type": "step", "icon": "🧠", "message": "Consultando memória de longo prazo..."})
            mem = await cc.agent_recall(question)
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
                action, payload = parse_agent_action(content)

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
                    exec_result = await asyncio.to_thread(rt.executor.run, payload)
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
                    found = await cc.agent_recall(payload, limit=4)
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

            answer = clean_agent_answer(answer)

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
                    verdict = clean_agent_answer(crit or "")
                    if verdict and verdict.upper() != "OK" and not verdict.upper().startswith("OK") and len(verdict) > 15:
                        answer = verdict  # adotou a versão refinada
                        yield _ev({"type": "step", "icon": "✨", "message": "Resposta refinada após autocrítica"})
                except Exception as e:
                    logger.debug(f"self-eval: {e}")

            # Emite a resposta final.
            yield _ev({"type": "token", "content": answer})

            # ── (2) Memória de longo prazo: guarda a solução para uso futuro ──
            if rt.rag and used_tools and answer.strip():
                try:
                    doc_id = f"agent_solution_{hash(question.strip().lower()) & 0xFFFFFFFF:08x}"
                    await asyncio.to_thread(
                        rt.rag.add_example,
                        f"# [SOLUÇÃO] {question[:120]}\nFonte: agente\n\n{answer[:2000]}", doc_id,
                    )
                except Exception as e:
                    logger.debug(f"save solution: {e}")

            # Persiste a conversa (igual ao chat).
            sess = rt.sessions[req.session_id]
            is_first = len(sess) == 0
            sess.append({"role": "user", "content": question})
            sess.append({"role": "assistant", "content": answer})
            rt.db.save_message(req.session_id, "user", question)
            rt.db.save_message(req.session_id, "assistant", answer)
            if is_first:
                asyncio.create_task(cc.generate_session_title(req.session_id, question))
            yield _ev({"type": "done", "answer": answer})
        except Exception as e:
            logger.error(f"Erro no agente: {e}", exc_info=True)
            yield _ev({"type": "error", "message": str(e)})

    return StreamingResponse(
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
