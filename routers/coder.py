"""A.P.O.L.O. Coder — o "Claude Code" interno: lê/escreve arquivos e roda comandos
num workspace isolado, em loop ReAct, até concluir a tarefa. Inclui planejamento,
guarda de regressão (com cache de baseline), pirâmide de conhecimento (CONSULTAR
base → BUSCAR_WEB → learn_from_web), reflexão pós-tarefa e diário de bordo.

Rota: /api/coder. Extraído de app.py na M1 do JARVIS_ROADMAP — o último e maior
endpoint a sair do monólito. Lê os singletons via runtime; usa coder_state (cache
de baseline + gpu_priority) e chat_common (ChatRequest, agent_recall).
"""
import asyncio
import json
import logging
import os
import re
import time as _time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src import runtime as rt
from src import chat_common as cc
from src.coder_state import baseline_cache, CODER_BASELINE_TTL, gpu_priority
from src.coder import extract_fenced, make_diff, compact_messages
from src.llm import chat_resilient, KEEP_ALIVE, KEEP_ALIVE_HEAVY
from src.utils import sanitize_request
from src.web_search import web_research
from src.prompts import (
    CODER_SYSTEM, CODER_DOCTRINE, CODER_TREE_SECTION,
    CODER_PLAN_PROMPT, CODER_REFLECT_PROMPT,
)

router = APIRouter()
logger = logging.getLogger("apolo.routers.coder")

MAX_CODER_STEPS = int(os.getenv("MAX_CODER_STEPS", 12))
CODER_CTX_CHARS = int(os.getenv("CODER_CTX_CHARS", 20000))
CODER_REFLECT = os.getenv("CODER_REFLECT", "1") not in ("0", "false", "False")


def parse_coder_action(content: str) -> tuple[str, str, str]:
    """Decide a ação do A.P.O.L.O. Coder. Retorna (tipo, arg, payload).
    tipos: 'edit' | 'write' | 'read' | 'list' | 'run' | 'done'."""
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
    # BUSCAR_WEB: <consulta> — busca na web (distinto de BUSCAR, que é grep no
    # workspace). Tratado ANTES do loop de verbos para não ser confundido com BUSC\w*.
    m_web = re.search(
        r"^[\s\d\.\)\-\*\#`>]*(?:BUSCAR_WEB|PESQUISAR_WEB|WEB)\s*:?\s+(.+)$",
        content, re.IGNORECASE | re.MULTILINE)
    if m_web:
        return "web", m_web.group(1).strip().strip("`").strip('"').strip(), ""
    for line in content.splitlines():
        # Tolera marcadores de lista/numeração que modelos leves adicionam ("1. ", "- ", "**").
        s = re.sub(r"^[\s\d\.\)\-\*\#`>]+", "", line).strip()
        # Verbos tolerantes a flexão/typo.
        m = re.match(r"(ESCREV\w*|LIST\w*|ROD\w*|BUSC\w*|ACH\w*|PROCUR\w*|APAG\w*|REMOV\w*|SUBSTITU\w*|MOV\w*|RENOME\w*|CONSULT\w*|LEMBR\w*|LER|LEIA)\s+(.+)", s, re.IGNORECASE)
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
                "MOVER" if raw.startswith("MOV") or raw.startswith("RENOME") else
                "CONSULTAR" if raw.startswith("CONSULT") or raw.startswith("LEMBR") else "LER")
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
        if verb == "CONSULTAR":
            return "consult", arg, ""
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


@router.post("/api/coder")
async def coder(req: cc.ChatRequest):
    """A.P.O.L.O. Coder — o "Claude Code" interno: lê/escreve arquivos e roda
    comandos num workspace isolado, em loop ReAct, até concluir a tarefa."""
    task = sanitize_request(req.message)
    # smart=True usa o 14b (raciocínio mais profundo p/ tarefas difíceis); senão o leve.
    model = rt.model if req.smart else rt.get_chat_model()
    keep = KEEP_ALIVE_HEAVY if req.smart else KEEP_ALIVE
    coder_ws = rt.coder_ws

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        answer = ""
        t0 = _time.time()
        try:
            # Barreira ANTES de gastar qualquer geração: workspace vazio (a pasta
            # padrão ./workspace, uma demo) não tem os arquivos que a tarefa
            # provavelmente pede. Sem isto, o Coder tenta ler o que não existe,
            # roda em loop de LER/LISTAR fracassados por minutos e no fim "conclui"
            # sem ter feito nada — visto ao vivo: reaproveitar uma tarefa antiga
            # com "Executar" depois de reiniciar o app (o ponteiro da cópia sandbox
            # é só memória de processo, zera no restart) caiu direto aqui.
            if await asyncio.to_thread(coder_ws.is_empty):
                yield _ev({"type": "error",
                           "message": "Workspace vazio — nada pra ler/editar aqui. Se você "
                                      "queria trabalhar numa cópia do projeto (automelhoria), "
                                      "clique 🧬 Auto-melhorar de novo (o ponteiro da cópia "
                                      "reseta a cada reinício do app). Ou selecione uma pasta "
                                      "com arquivos em 📁 Pasta / Procurar."})
                return
            system_content = CODER_SYSTEM + CODER_DOCTRINE + CODER_TREE_SECTION.format(tree=coder_ws.tree())
            # Memória de Projeto: se há um projeto memorizado (🎯), o Coder conhece
            # a stack/dependências desde o 1º passo — mesmo contexto que o chat usa.
            if rt.project_mem:
                _proj_sec = rt.project_mem.as_prompt_section()
                if _proj_sec:
                    system_content += _proj_sec
            # ── Autoaprendizado: injeta lições de tarefas anteriores parecidas ──
            # O Coder lê a própria experiência (regressões revertidas, reflexões)
            # antes de agir — mesmo mecanismo de memória do Claude Code.
            if rt.lesson_mem:
                lessons_block = await asyncio.to_thread(rt.lesson_mem.format_section, task)
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
                _cached = baseline_cache.get(_root)
                if _cached and (_time.time() - _cached[1]) < CODER_BASELINE_TTL:
                    baseline_green = _cached[0]
                    yield _ev({"type": "step", "icon": "🛡️",
                               "message": f"Baseline em cache ({int(_time.time() - _cached[1])}s atrás): "
                                          f"testes {'PASSANDO' if baseline_green else 'vermelhos (guarda desativada)'} — suíte não re-rodada"})
                else:
                    yield _ev({"type": "step", "icon": "🛡️", "message": "Guarda de regressão: verificando a suíte de testes (baseline)..."})
                    baseline_green, _ = await asyncio.to_thread(coder_ws.run_cmd, "python -m pytest -q", 300)
                    baseline_cache[_root] = (baseline_green, _time.time())
                    yield _ev({"type": "step", "icon": "🛡️",
                               "message": f"Baseline: testes {'PASSANDO' if baseline_green else 'já vermelhos (guarda desativada)'}"})

            wrote_files = False
            did_run = False
            nudged = False
            reverted = False
            rescue_used = False          # resgate único p/ resposta sem ação válida
            last_sig: tuple = ("", "")   # anti-loop: última (ação, alvo) executada
            repeat_count = 0
            edit_fail_streak = 0         # EDITAR falhando seguido → empurra p/ ESCREVER
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
                if rt.gpu_gate and req.smart:
                    await rt.gpu_gate.wait_for_idle()
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
                action, arg, payload = parse_coder_action(content)
                steps_used = step + 1

                if action == "done":
                    # Resgate único: o modelo despejou código solto (bloco ``` sem
                    # ESCREVER/EDITAR), marcadores de EDITAR mal-formados (<<<<<<< sem
                    # virar uma ação "edit" reconhecida — visto ao vivo: a "conclusão"
                    # era literalmente um EDITAR cru cortado no meio) ou veio vazio —
                    # sem isto, a tarefa "concluía" mostrando lixo como se fosse resumo.
                    stray_code = (("```" in content or "<<<<<<<" in content)
                                 and "CONCLU" not in content.upper())
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
                    # O resgate é único (evita loop infinito) — mas mesmo sem resgate
                    # sobrando, uma resposta que ainda é lixo (marcadores de EDITAR
                    # cru, sem CONCLUIR) NUNCA vira "✅ Concluído" como se fosse um
                    # resumo de verdade. Honesto > bonito.
                    answer = (content if not stray_code else
                              "Não consegui concluir com um resumo válido — a última "
                              "tentativa de edição falhou e nada foi escrito. "
                              "Veja o histórico de passos acima para o detalhe.")
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
                elif action == "consult":
                    # CONSULTAR <pergunta> — o Coder consulta a base de conhecimento
                    # (RAG) do que a IA já estudou/produziu. Fecha o ciclo learner→coder:
                    # ao travar num erro ou conceito, ele pergunta à própria memória.
                    yield _ev({"type": "step", "icon": "📚", "message": f"CONSULTAR base: {arg[:60]}"})
                    mem = await cc.agent_recall(arg, limit=4)
                    if mem:
                        obs = (f"O que a IA já aprendeu sobre '{arg}':\n\n{mem}\n\n"
                               "Use isto para decidir a próxima ação (não repita a mesma CONSULTAR).")
                    else:
                        # Lacuna de conhecimento: o Coder perguntou algo que a IA nunca
                        # estudou → registra como prioridade de estudo (loud coder→learner).
                        if rt.learner:
                            try:
                                rt.learner.note_gap(arg)
                                rt.learner.add_user_topic(arg)
                            except Exception:
                                pass
                        obs = (f"A base não tem nada relevante sobre '{arg}' (registrei como lacuna "
                               "para a IA estudar depois). Use BUSCAR_WEB para pesquisar na web, "
                               "ou siga com LER/BUSCAR no workspace.")
                elif action == "web":
                    # BUSCAR_WEB <consulta> — pesquisa na web (fatos atuais, docs, APIs
                    # que nem a base local tem). Mesma infra do chat (web_research).
                    yield _ev({"type": "step", "icon": "🌐", "message": f"BUSCAR_WEB: {arg[:60]}"})
                    try:
                        web_ctx, srcs = await asyncio.wait_for(
                            web_research(arg, max_results=3), timeout=20.0)
                    except Exception:
                        web_ctx, srcs = "", []
                    yield _ev({"type": "step", "icon": "✓" if web_ctx else "✗",
                               "message": f"{len(srcs)} fonte(s)" if srcs else "sem resultados"})
                    if web_ctx:
                        # Enriquece a base: o que o Coder achou na web vira conhecimento
                        # PERMANENTE (sintetizado, em background) → a próxima CONSULTAR
                        # já encontra e ele nunca pesquisa a mesma coisa duas vezes.
                        if rt.learner:
                            asyncio.create_task(rt.learner.learn_from_web(arg, web_ctx))
                            yield _ev({"type": "step", "icon": "📥",
                                       "message": "Salvando na base para não pesquisar de novo..."})
                        obs = (f"Resultado da web sobre '{arg}':\n\n{web_ctx[:1800]}\n\n"
                               "Use isto para agir (aplique no código com EDITAR/ESCREVER). "
                               "NÃO repita a mesma BUSCAR_WEB.")
                    else:
                        obs = (f"A web não retornou nada útil sobre '{arg}'. "
                               "Resolva pelo raciocínio ou inspecione o workspace (LER/BUSCAR).")
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
                        edit_fail_streak = 0
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
                        edit_fail_streak += 1
                        yield _ev({"type": "step", "icon": "✗", "message": f"EDITAR {arg} — {out[:80]}"})
                    chk = await _syntax_check(arg) if out.startswith("OK") else ""
                    if chk:
                        yield _ev({"type": "step", "icon": "🧪",
                                   "message": f"py_compile falhou em {arg} — devolvendo o erro ao modelo"})
                    actions_log.append(
                        f"EDITAR {arg} → {'ok' if out.startswith('OK') else 'FALHOU: ' + out[:100]}"
                        + (" (sintaxe quebrada detectada)" if chk else ""))
                    # EDITAR falhou 2x seguidas no mesmo alvo (mesmo com a dica do trecho
                    # mais parecido) → o problema não é "quase acertou", é o modelo não
                    # conseguir reproduzir texto EXATO. Empurra pra ESCREVER (reescreve o
                    # arquivo inteiro, sem exigir match) em vez de deixar o loop repetir a
                    # mesma falha até estourar os passos (visto ao vivo: 3 falhas seguidas,
                    # 0 mudanças, ~50min gastos). Reseta pra dar mais uma chance depois.
                    if edit_fail_streak >= 2:
                        edit_fail_streak = 0
                        obs = (out + chk + "\n\n⚠️ EDITAR falhou 2 vezes seguidas neste arquivo — "
                               "pare de tentar EDITAR. Use ESCREVER (reescreva o arquivo INTEIRO "
                               "com a mudança já aplicada) — não exige texto exato.")
                    else:
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
                        edit_fail_streak = 0
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

            answer = re.sub(r"^[\s*#>`-]*CONCLUIR\s*:?\s*", "", answer, flags=re.IGNORECASE).strip()

            # Guarda de regressão (a rede de proteção): se escreveu arquivos e a suíte
            # estava verde no início, ela PRECISA continuar verde. Senão, desfaz tudo.
            if wrote_files and has_tests and baseline_green:
                yield _ev({"type": "step", "icon": "🛡️", "message": "Guarda de regressão: revalidando a suíte após as alterações..."})
                final_green, final_out = await asyncio.to_thread(coder_ws.run_cmd, "python -m pytest -q", 300)
                if final_green:
                    baseline_cache[_root] = (True, _time.time())
                else:
                    # Revert restaura os arquivos, mas re-mede na próxima tarefa.
                    baseline_cache.pop(_root, None)
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
                    if rt.lesson_mem:
                        await asyncio.to_thread(
                            rt.lesson_mem.add, task,
                            f"Em tarefa parecida, minhas mudanças quebraram a suíte e foram "
                            f"revertidas (erro: {tail[-180:].strip()}). Rodar os testes relacionados "
                            f"ANTES de concluir e preferir EDITAR cirúrgico a reescrever.",
                            "regression")
                        yield _ev({"type": "step", "icon": "🧠",
                                   "message": "Lição de regressão registrada — não vou repetir esse erro."})
                    # 2) Loop fechado Coder → Learner: o tema da falha vira estudo
                    #    prioritário do autoaprendizado (fecha o ciclo de autonomia).
                    if rt.learner:
                        rt.learner.note_gap(task)
                        rt.learner.add_user_topic(task)
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
            if CODER_REFLECT and rt.lesson_mem and wrote_files and not reverted and actions_log:
                try:
                    outcome = "\n".join(actions_log[-15:])[:2500]
                    refl = (await asyncio.to_thread(
                        chat_resilient, rt.get_chat_model(),
                        [{"role": "user", "content":
                          CODER_REFLECT_PROMPT.format(task=task[:300], outcome=outcome)}],
                        keep_alive=KEEP_ALIVE) or "").strip()
                    if refl and not refl.upper().startswith("NONE") and len(refl) >= 15:
                        saved = await asyncio.to_thread(
                            rt.lesson_mem.add, task, refl[:600], "reflection")
                        if saved:
                            yield _ev({"type": "step", "icon": "🧠",
                                       "message": f"Lição aprendida: {refl[:120]}"})
                except Exception as _refl_err:
                    logger.debug(f"coder reflect: {_refl_err}")

            # Diário de bordo: cada tarefa vira um registro persistente (passos,
            # duração, escreveu/rodou/revertida) — autonomia visível + matéria-prima
            # para acompanhar a taxa de sucesso do Coder ao longo do tempo.
            if rt.db:
                try:
                    await asyncio.to_thread(
                        rt.db.save_coder_task, task, model, steps_used, wrote_files,
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
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
