"""Modularização do frontend (Épico 1.2 do JARVIS_ROADMAP): o monólito
static/index.html (5.401 linhas) está sendo quebrado em CSS/JS externos.

Estes testes travam o contrato da extração — o navegador precisa continuar
recebendo exatamente os mesmos recursos, servidos pelo StaticFiles montado em
"/". Crescem a cada incremento (próximo: módulos JS).
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)
STATIC = Path(__file__).resolve().parents[1] / "static"


def test_css_extraido_para_arquivo_externo():
    css = STATIC / "css" / "app.css"
    assert css.exists(), "CSS deveria estar em static/css/app.css"
    assert css.stat().st_size > 0


def test_index_referencia_css_externo_e_nao_tem_style_inline():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '/css/app.css' in html, "index.html deve linkar o CSS externo"
    # A extração só está completa se o <style> inline sumiu do HTML.
    assert "<style>" not in html


def test_css_servido_pelo_static_mount():
    r = client.get("/css/app.css")
    assert r.status_code == 200
    assert "css" in r.headers["content-type"]
    # Sanidade: as variáveis de tema (que dão a cara do app) vieram junto.
    assert "--bg:" in r.text


def test_js_extraido_para_arquivos_externos():
    for name in ("app.js", "enhancements.js"):
        js = STATIC / "js" / name
        assert js.exists(), f"JS deveria estar em static/js/{name}"
        assert js.stat().st_size > 0


def test_index_referencia_js_externo_e_nao_tem_script_inline():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '/js/app.js' in html and '/js/enhancements.js' in html
    # Extração completa: nenhum bloco <script> inline sobrou (só <script src=...>).
    # Todo <script no HTML deve ter atributo src.
    import re
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag, f"bloco <script> inline não deveria existir: {tag}"


def test_js_servido_pelo_static_mount():
    for name, marker in (("app.js", "marked.setOptions"),
                         ("enhancements.js", "startLearnSSE")):
        r = client.get(f"/js/{name}")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]
        assert marker in r.text


def test_ordem_de_carregamento_satisfaz_dependencias_de_boot():
    """O boot de app.js chama _initTabs()/startLearnSSE(), definidas em
    enhancements.js. Declarações de função NÃO cruzam <script> tags, então
    enhancements.js precisa carregar ANTES de app.js — senão o boot aborta
    com ReferenceError (bug latente que a modularização corrigiu)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("/js/enhancements.js") < html.index("/js/app.js")


def test_painel_de_permissoes_esta_ligado():
    """M6 6.1 — a tela de consentimento precisa do botão + funções de grant/revoke."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openPermissions()"' in html and 'id="perm-overlay"' in html
    for fn in ("function openPermissions", "function togglePermission", "/api/permissions"):
        assert fn in app_js


def test_grant_escopos_de_caminho_pedem_a_allowlist():
    """M6 6.2/6.3 — autorizar 'files.read' (pasta) e 'calendar.read' (.ics) precisa
    capturar QUAL caminho (a allowlist, enviada como note). Caminhos do Windows têm
    '\\' e não podem ser inlinados no onclick, então o toggle busca a note em
    _permScopes e roteia os escopos-de-caminho por _grantScopePath."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "_grantScopePath" in app_js and "_permScopes" in app_js
    # ambos os escopos-de-caminho estão no mapa que dispara o prompt de caminho
    assert "'files.read'" in app_js and "'calendar.read'" in app_js
    assert "_SCOPE_PATH" in app_js
    # o grant manda a note (caminho) no corpo
    assert "scope, note: path" in app_js


def test_painel_de_auditoria_esta_ligado():
    """Épico 1.3 — o painel 'Atividade (24h)' precisa do botão no HTML e das
    funções de abertura/carregamento no JS."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openAudit()"' in html
    assert 'id="audit-overlay"' in html
    for fn in ("function openAudit", "function loadAudit", "/api/audit"):
        assert fn in app_js


def test_verificacao_anti_alucinacao_ligada():
    """M7 7.2 — respostas factuais passam por /api/verify e, se não estiverem
    ancoradas na base, ganham um aviso de incerteza (.verify-chip)."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert "function verifyAndBadge" in app_js and "/api/verify" in app_js
    assert "verifyAndBadge(aiWrap, text, acc)" in app_js   # chamado ao finalizar
    assert ".verify-chip" in css


def test_roteador_de_tarefa_ligado():
    """M7 7.1 — comando de agência curto é roteado por /api/route → /api/agency/ask
    (sem gastar o LLM), antes do envio normal ao chat."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "function _tryAgencyCommand" in app_js and "/api/route" in app_js
    assert "await _tryAgencyCommand(text)" in app_js
    # M8 8.3: pergunta de conexão ("como X se conecta com Y") → /api/graph/connect
    assert "'connect'" in app_js and "/api/graph/connect" in app_js


def test_painel_saude_mostra_apolo_nano():
    """APOLO_NANO_ROADMAP 3.2 — o painel 🩺 Saúde precisa do cartão da LLM
    própria (bloco h.nano do /api/health), incluído no innerHTML do painel."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "🧬 Apolo-Nano" in app_js
    assert "h.nano" in app_js
    # o cartão precisa entrar no innerHTML DO PAINEL DE SAÚDE (linha que
    # monta o painel final — contém "ollamaCard" e "nanoCard" concatenados)
    saude_render = next(ln for ln in app_js.splitlines()
                        if "body.innerHTML =" in ln and "ollamaCard" in ln)
    assert "nanoCard" in saude_render


def test_painel_perfil_curadoria_completa():
    """M16.1/16.2/16.3 — o painel Sobre mim mostra o modelo agrupado (by_category),
    os candidatos a confirmar/descartar, e o editor inline (curado por você)."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    # M16.1: agrupamento por seção
    assert "by_category" in app_js and "pf-sec" in css
    # M16.2: candidatos
    for fn in ("confirmCandUI", "rejectCandUI", "/api/profile/candidates"):
        assert fn in app_js, fn
    # M16.3: editor inline usa o PATCH
    for fn in ("function editFactUI", "function saveFactEdit", "'PATCH'"):
        assert fn in app_js, fn
    assert ".pf-edit" in css and ".pf-ed-input" in css


def test_painel_linha_do_tempo_ligado():
    """M18 — o painel 📜 Linha do tempo: a memória relacional. Botão + overlay,
    a caixa de recall relacional (/api/recall) e as duas abas (linha do tempo /
    pessoas) consumindo /api/timeline e /api/people."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert 'onclick="openTimeline()"' in html and 'id="timeline-overlay"' in html
    assert 'onclick="askRecall()"' in html
    for fn in ("function openTimeline", "function loadTimeline", "function loadPeople",
               "function askRecall", "function switchTimelineTab",
               "/api/timeline", "/api/people", "/api/recall"):
        assert fn in app_js, fn
    # botão de nav com estilo do tema (não fica branco) + chips das entidades
    assert "#timeline-open-btn" in css and ".tl-chip" in css


def test_painel_acoes_reversiveis_ligado():
    """M10 10.1 — o painel 🛠️ Ações precisa do botão, do fluxo preview→confirmar
    e do histórico com desfazer (a trilha reversível). Confirmar só habilita
    DEPOIS da prévia (nunca modifica num clique só)."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert 'onclick="openActions()"' in html and 'id="actions-overlay"' in html
    assert 'id="act-confirm-btn"' in html and 'disabled' in html   # confirmar começa travado
    for fn in ("function openActions", "function previewWriteAction",
               "function confirmWriteAction", "function undoLedgerItem",
               "/api/actions/preview", "/api/actions/confirm", "/api/actions/undo"):
        assert fn in app_js, fn
    assert "#actions-open-btn" in css                              # não fica branco


def test_mover_organizar_arquivo_ligado():
    """M21.1 — o painel 🛠️ Ações ganha o console de MOVER/organizar arquivo, no
    mesmo fluxo preview→confirmar→desfazer (kind files.move), reversível."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="mv-src"' in html and 'id="mv-dst"' in html
    assert 'onclick="previewMoveAction()"' in html and 'id="mv-confirm-btn"' in html
    for fn in ("function previewMoveAction", "function confirmMoveAction", "'files.move'"):
        assert fn in app_js, fn


def test_projetos_autodirigidos_ligados():
    """M12 12.1 — o painel 🎯 Projetos: sugestões (das próprias métricas) + adotar +
    checklist de passos, consumindo /api/projects*."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert 'onclick="openProjects()"' in html and 'id="projects-overlay"' in html
    for fn in ("function openProjects", "function loadSuggestions", "function adoptProject",
               "function toggleProjectTask", "/api/projects/suggest", "/api/projects/adopt"):
        assert fn in app_js, fn
    assert "#projects-open-btn" in css


def test_execucao_supervisionada_de_passos_ligada():
    """M19.1 — o painel 🎯 Projetos ganha a EXECUÇÃO dos passos: cada projeto
    lista os passos que o Apolo roda sozinho, no contrato preview→executar,
    consumindo /api/projects/{id}/plan e .../steps/{key}/preview|run."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    for fn in ("function loadPlan", "function previewStepUI", "function runStepUI",
               "/plan", "/steps/", "/preview", "/run"):
        assert fn in app_js, fn
    assert ".pe-step" in css and ".pe-run" in css
    # M19.2: plano multi-passo com checkpoints
    assert "function runPlanUI" in app_js and "/plan/run" in app_js
    assert "needs_confirmation" in app_js and ".pe-ckpt" in css
    # M19.3: propõe→faz→mede (antes→depois)
    assert "function loadOutcome" in app_js and "/outcome" in app_js
    assert ".pe-outcome" in css


def test_retrospectiva_do_ano_ligada():
    """M12 12.2 — o painel 🎯 Projetos tem a retrospectiva do ano com botão de FALAR
    (DoD do M12: apresenta por voz), consumindo /api/retrospective."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="retro-body"' in html and 'onclick="speakRetrospective()"' in html
    for fn in ("function loadRetrospective", "function speakRetrospective", "/api/retrospective"):
        assert fn in app_js, fn
    assert "speak(_retroText)" in app_js       # fala a retrospectiva (voz)


def test_embeddings_soberania_no_painel_saude():
    """M11 11.1 — o painel Saúde mostra a soberania dos embeddings (local/offline),
    consumindo /api/embeddings/info."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "/api/embeddings/info" in app_js
    assert "Embeddings (soberania)" in app_js


def test_acesso_remoto_ligado():
    """M11 11.3 — o modal 📱 Acesso remoto precisa do gatilho + o carregamento das
    infos (URL da LAN + token), consumindo /api/remote/info."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openRemote()"' in html and 'id="remote-overlay"' in html
    for fn in ("function openRemote", "function loadRemoteInfo", "/api/remote/info"):
        assert fn in app_js, fn


def test_backup_criptografado_ligado():
    """M11 11.2 — o modal 🔒 Backup cifrado precisa do gatilho + funções de criar/
    restaurar/listar, consumindo /api/backup/*."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openBackup()"' in html and 'id="backup-overlay"' in html
    for fn in ("function openBackup", "function createEncryptedBackup",
               "function restoreEncryptedBackup", "function loadBackupStatus",
               "/api/backup/encrypted", "/api/backup/restore", "/api/backup/status"):
        assert fn in app_js, fn


def test_automacao_web_ligada():
    """M10 10.3 — o painel 🛠️ Ações tem o console de automação web (prévia valida
    a sandbox, executar roda a receita read-only), consumindo /api/webtask/*."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="web-recipe"' in html and 'onclick="planWebTask()"' in html and 'onclick="runWebTask()"' in html
    for fn in ("function planWebTask", "function runWebTask",
               "/api/webtask/plan", "/api/webtask/run"):
        assert fn in app_js, fn


def test_navegador_interativo_ligado():
    """M20.1 — o painel 🛠️ Ações ganha o console do navegador INTERATIVO
    (clicar/preencher/enviar), com prévia de cada passo e confirmação dos passos
    de efeito, consumindo /api/webtask/interactive/*."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="iweb-recipe"' in html and 'onclick="planInteractive()"' in html
    assert 'onclick="runInteractive()"' in html and 'id="iweb-confirm"' in html
    for fn in ("function planInteractive", "function runInteractive",
               "/api/webtask/interactive/plan", "/api/webtask/interactive/run",
               "needs_confirmation"):
        assert fn in app_js, fn
    # M20.2: trilha durável de efeitos
    assert "function loadInteractiveTrail" in app_js and "/api/webtask/interactive/trail" in app_js
    assert 'id="iweb-trail"' in html


def test_rotinas_automatizadas_ligadas():
    """M10 10.2 — o painel 🛠️ Ações também gerencia rotinas: criar/listar/rodar-
    agora/pausar/remover, consumindo /api/routines. Abrir o painel carrega as rotinas."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'id="rot-list"' in html and 'onclick="createRoutine()"' in html
    for fn in ("function loadRoutines", "function createRoutine", "function runRoutineNow",
               "function toggleRoutine", "function deleteRoutine", "/api/routines"):
        assert fn in app_js, fn
    assert "loadRoutines();" in app_js          # openActions carrega as rotinas


def test_painel_estou_melhorando_ligado():
    """M9 9.3 — o painel Analytics abre com o card 'Estou melhorando?' (veredito +
    eixos + sparkline) alimentado por /api/improving, e o botão que roda o canário."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    assert "function _loadImproving" in app_js and "/api/improving" in app_js
    assert "_loadImproving();" in app_js                       # chamado ao abrir Analytics
    assert "function runCanaryFromAnalytics" in app_js and "/api/evals/run" in app_js
    assert 'id="an-improving"' in app_js and ".an-axis" in css


def test_feedback_por_que_no_polegar_para_baixo():
    """M9 9.2 — o 👎 precisa pedir o 'por quê' e mandar pergunta+resposta+motivo,
    senão o feedback vira só um contador (não é acionável para melhoria/memória)."""
    enh = (STATIC / "js" / "enhancements.js").read_text(encoding="utf-8")
    assert "window.prompt(" in enh                      # pede o motivo
    assert "reason" in enh and "question: q" in enh and "answer: text" in enh
    # captura a pergunta que gerou ESTA resposta (não a última digitada depois)
    assert "lastUserText" in enh


def test_wake_word_ui_ligada():
    """M5 5.1 — o botão 👂 e a escuta contínua que chama /api/wake/detect e
    despacha o comando por /api/agency/ask precisam estar no frontend."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="toggleWakeWord()"' in html and 'id="wake-btn"' in html
    for marker in ("function toggleWakeWord", "/api/wake/detect", "/api/agency/ask",
                   "continuous = true"):
        assert marker in app_js
    # barge-in (5.2): começar a falar corta a fala do assistente
    assert "onspeechstart" in app_js and "speechSynthesis.cancel()" in app_js


def test_applylearnstatus_existe_para_o_stream_sse():
    """O painel de aprendizado é alimentado pelo push SSE:
    startLearnSSE() (enhancements.js) chama applyLearnStatus(payload). Se essa
    função não existir, cada evento vira ReferenceError silencioso (o onmessage
    tem catch {}) e o dashboard congela em 'aguardando...' — foi o bug reportado.
    Trava a existência da função E o bootstrap imediato no boot."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    enh = (STATIC / "js" / "enhancements.js").read_text(encoding="utf-8")
    # o consumidor do SSE chama applyLearnStatus...
    assert "applyLearnStatus(" in enh
    # ...e o produtor (app.js) precisa defini-la como declaração global.
    assert "function applyLearnStatus" in app_js
    # boot faz bootstrap imediato (não espera o 1º tick do SSE / navegador sem EventSource)
    assert "refreshLearnStatus();" in app_js and "startLearnSSE();" in app_js


def test_botoes_de_nav_novos_tem_estilo_do_tema():
    """Regressão visual: #audit-open-btn e #perm-open-btn foram adicionados como
    <button> sem classe. O visual dos itens da sidebar vem de regras por ID no
    CSS — se o ID novo não entrar na regra, o botão cai no default do navegador
    (fundo branco, texto preto) e destoa do tema escuro. Garante que ambos estão
    na regra compartilhada de botão de navegação."""
    css = (STATIC / "css" / "app.css").read_text(encoding="utf-8")
    import re
    # localiza a regra base dos botões de nav (a que define 'border-top:1px solid var(--border)')
    nav_rule = next(
        (line for line in css.splitlines()
         if "#analytics-open-btn" in line and "border-top:1px solid var(--border)" in line),
        "",
    )
    assert "#audit-open-btn" in nav_rule, "botão Atividade fora da regra de nav → fica branco"
    assert "#perm-open-btn" in nav_rule, "botão Permissões fora da regra de nav → fica branco"
    # e cada um tem seu hover (feedback de interação como os demais)
    assert re.search(r"#audit-open-btn:hover", css)
    assert re.search(r"#perm-open-btn:hover", css)


def test_js_css_tem_cache_control_no_cache():
    """StaticFiles manda ETag mas não Cache-Control → navegador cacheia por
    heurística e serve código velho após update. O middleware força `no-cache`
    (revalida via ETag, barato) no JS/CSS do app — garante UI fresca."""
    for path in ("/js/app.js", "/css/app.css", "/js/enhancements.js"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-cache", path


def test_handsfree_usa_tts_do_servidor_para_qualquer_engine():
    """Loop conversacional (M3 3.3): o modo mãos-livres deve usar o TTS do
    servidor para QUALQUER engine != browser (Piper local OU edge nuvem). O bug
    antigo só reconhecia 'edge-tts' e ignorava o Piper (voz soberana)."""
    js = (STATIC / "js" / "enhancements.js").read_text(encoding="utf-8")
    assert "useEdgeTts" not in js                         # lógica antiga removida
    assert "HF.useServerTts = HF.ttsEngine !== 'browser'" in js
    # envia o rótulo da voz (feminino/masculino), que a fachada mapeia por engine
    assert "voice:HF.hfVoice" in js


def test_sw_nao_serve_js_css_do_app_desatualizado():
    """Com JS/CSS em arquivos externos (Épico 1.2), o service worker precisa
    tratá-los como network-first — senão o cache-first serve código velho para
    sempre depois de um update. Guarda essa regressão."""
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    body = sw.text
    # trata .js/.css do próprio domínio junto do HTML (network-first)
    assert ".endsWith('.js')" in body and ".endsWith('.css')" in body
    assert "isAppCode" in body
