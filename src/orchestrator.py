"""Orquestrador de sub-agentes especializados do A.P.O.L.O.

Decompõe tarefas complexas em sub-tarefas, distribui para especialistas
com system prompts focados e sintetiza os resultados num entregável coeso.

Em hardware CPU-only os agentes rodam SEQUENCIALMENTE (não há RAM para 2
modelos simultâneos). O usuário vê o progresso de cada especialista ao vivo.

Especialistas disponíveis:
  researcher — busca, síntese de conhecimento, citações
  analyst    — raciocínio, comparação, trade-offs, estrutura
  coder      — implementação, código limpo, debugging
"""

import logging
import re

logger = logging.getLogger(__name__)

# ── Prompts dos especialistas ──────────────────────────────────────────────────

_DECOMPOSE_PROMPT = """\
Analise a tarefa abaixo e decida como ela deve ser tratada.

Se for simples (pergunta direta, fato, código trivial) → escreva APENAS:
DIRETO: <sua resposta completa>

Se for complexa → decomponha em sub-tarefas para os especialistas:
RESEARCHER: <o que pesquisar / sintetizar do conhecimento>
ANALYST: <o que analisar / comparar / raciocinar>
CODER: <o que implementar / exemplificar em código>

Use apenas os especialistas necessários (pode ser só 1, não precisa usar os 3).
Escreva APENAS o plano, sem executar nada ainda.

Tarefa: {task}"""

_SPECIALIST_SYSTEM: dict[str, str] = {
    "researcher": """\
Você é o sub-agente RESEARCHER do A.P.O.L.O. Sua única função é:
- Sintetizar conhecimento técnico preciso e profundo
- Citar fontes ou documentação oficial quando relevante
- Dar contexto histórico/evolutivo se ajudar a entender
Seja factual, denso e organizado. Responda APENAS à sub-tarefa dada, \
sem implementar código completo (isso é responsabilidade do CODER).""",

    "analyst": """\
Você é o sub-agente ANALYST do A.P.O.L.O. Sua única função é:
- Raciocinar sobre trade-offs, vantagens e desvantagens
- Estruturar comparações com critérios claros (tabelas quando útil)
- Chegar a recomendações fundamentadas e objetivas
Seja assertivo e estruturado. Responda APENAS à sub-tarefa dada.""",

    "coder": """\
Você é o sub-agente CODER do A.P.O.L.O. Sua única função é:
- Escrever código limpo, testável e production-ready
- Incluir type hints, tratamento de erro e comentários onde necessário
- Seguir as melhores práticas da linguagem (PEP 8 para Python etc.)
Seja direto: código primeiro, explicação mínima depois. \
Responda APENAS à sub-tarefa de implementação.""",
}

_SYNTHESIZE_PROMPT = """\
Você é o A.P.O.L.O. orquestrando sua própria equipe de especialistas.
Abaixo estão as contribuições de cada sub-agente para a tarefa original.

Tarefa original: {task}

{contributions}

Sintetize tudo numa resposta ÚNICA, coerente e completa para o usuário.
- Integre código e explicações de forma fluida
- Elimine redundâncias
- Responda em português brasileiro
- Não mencione os sub-agentes pelo nome na resposta final"""

_ICON = {"researcher": "🔬", "analyst": "💡", "coder": "💻"}
_LABEL = {"researcher": "Researcher", "analyst": "Analyst", "coder": "Coder"}


# ── Parser do plano ────────────────────────────────────────────────────────────

def parse_plan(text: str) -> dict:
    """Retorna {'direct': str} ou {'tasks': [(specialist, sub_task), ...]}."""
    # Resposta direta
    m = re.search(r"^DIRETO:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return {"direct": m.group(1).strip()}
    # Sub-tarefas
    tasks = []
    for sp in ("researcher", "analyst", "coder"):
        m2 = re.search(rf"^{sp}:\s*(.+?)(?=^(?:researcher|analyst|coder):|$)",
                       text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if m2:
            sub = m2.group(1).strip()
            if sub:
                tasks.append((sp, sub))
    return {"tasks": tasks} if tasks else {"direct": text.strip()}


# ── Função principal (gerador de eventos SSE) ──────────────────────────────────

async def orchestrate(
    task: str,
    chat_model: str,
    heavy_model: str,
    keep_light: str,
    keep_heavy: str,
    rag=None,
    knowledge_db=None,
):
    """Gerador assíncrono de dicts de evento para o endpoint SSE.

    Yields dicts: {'type': 'step'|'agent_start'|'agent_token'|'done', ...}
    """
    from src.llm import chat_resilient, stream_chat
    import asyncio

    def _ev(type_: str, **kw) -> dict:
        return {"type": type_, **kw}

    yield _ev("step", icon="🎯", message="Analisando a tarefa e montando o plano...")

    # ── Fase 1: decomposição ───────────────────────────────────────────────────
    decompose_prompt = _DECOMPOSE_PROMPT.format(task=task)
    plan_raw = await asyncio.to_thread(
        chat_resilient, chat_model,
        [{"role": "user", "content": decompose_prompt}],
        keep_alive=keep_light, options={"num_predict": 300},
    ) or ""
    plan = parse_plan(plan_raw.strip())

    # Resposta direta (tarefa simples — nenhum especialista necessário)
    if "direct" in plan:
        yield _ev("step", icon="⚡", message="Tarefa simples — resposta direta (sem delegação)")
        yield _ev("agent_start", specialist="direct", label="A.P.O.L.O.")
        full = ""
        async for token in stream_chat(chat_model, [{"role": "user", "content": task}], keep_alive=keep_light):
            full += token
            yield _ev("agent_token", specialist="direct", content=token)
        yield _ev("done", answer=full, specialists_used=[])
        return

    tasks: list[tuple[str, str]] = plan["tasks"]
    if not tasks:
        yield _ev("step", icon="⚠️", message="Não consegui decompor — respondendo diretamente")
        yield _ev("agent_start", specialist="direct", label="A.P.O.L.O.")
        full = ""
        async for token in stream_chat(chat_model, [{"role": "user", "content": task}], keep_alive=keep_light):
            full += token
            yield _ev("agent_token", specialist="direct", content=token)
        yield _ev("done", answer=full, specialists_used=[])
        return

    specialists_used = [sp for sp, _ in tasks]
    yield _ev("step", icon="📋", message=f"Plano: {' → '.join(_LABEL[s] for s in specialists_used)}")

    # ── Fase 2: execução sequencial dos especialistas ──────────────────────────
    contributions: list[str] = []
    for specialist, sub_task in tasks:
        icon = _ICON.get(specialist, "🤖")
        label = _LABEL.get(specialist, specialist.title())
        yield _ev("step", icon=icon, message=f"{label}: {sub_task[:80]}")
        yield _ev("agent_start", specialist=specialist, label=label)

        # Coder e Researcher com contexto RAG se disponível
        rag_ctx = ""
        if rag and specialist in ("researcher", "analyst"):
            try:
                hits = await asyncio.to_thread(rag.recall, sub_task, 2)
                if hits:
                    rag_ctx = "\n\n".join(
                        f"[memória] {h.get('title', '')}: {h.get('snippet', '')[:300]}"
                        for h in hits if h.get("relevance", 0) > 0.2
                    )
            except Exception:
                pass
        if knowledge_db and specialist == "researcher":
            try:
                kb_ctx = await asyncio.to_thread(knowledge_db.format_context, sub_task)
                if kb_ctx:
                    rag_ctx = (rag_ctx + "\n\n" + kb_ctx).strip()
            except Exception:
                pass

        system = _SPECIALIST_SYSTEM[specialist]
        if rag_ctx:
            system += f"\n\nConhecimento relevante da memória:\n{rag_ctx[:800]}"

        # Coder usa o modelo pesado para qualidade máxima; outros usam o leve
        model = heavy_model if specialist == "coder" else chat_model
        keep = keep_heavy if specialist == "coder" else keep_light

        response = ""
        async for token in stream_chat(
            model,
            [{"role": "system", "content": system},
             {"role": "user", "content": sub_task}],
            keep_alive=keep,
        ):
            response += token
            yield _ev("agent_token", specialist=specialist, content=token)

        contributions.append(f"### {label}\n{response.strip()}")
        yield _ev("step", icon="✓", message=f"{label} concluído ({len(response)} chars)")

    # ── Fase 3: síntese ───────────────────────────────────────────────────────
    if len(contributions) > 1:
        yield _ev("step", icon="🔀", message="Sintetizando contribuições dos especialistas...")
        synth_prompt = _SYNTHESIZE_PROMPT.format(
            task=task,
            contributions="\n\n".join(contributions),
        )
        final = ""
        yield _ev("agent_start", specialist="synthesis", label="Síntese Final")
        async for token in stream_chat(
            heavy_model,
            [{"role": "user", "content": synth_prompt}],
            keep_alive=keep_heavy,
        ):
            final += token
            yield _ev("agent_token", specialist="synthesis", content=token)
    else:
        # Só 1 especialista → resposta já é a final
        final = contributions[0].split("\n", 1)[-1].strip() if contributions else ""
        yield _ev("agent_token", specialist="direct", content=final)

    yield _ev("done", answer=final, specialists_used=specialists_used)
