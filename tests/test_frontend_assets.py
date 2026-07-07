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


def test_grant_files_read_pede_a_pasta_autorizada():
    """M6 6.2 — autorizar 'files.read' precisa capturar QUAL pasta (a allowlist,
    enviada como note). O caminho não pode ser inlinado no onclick (backslash do
    Windows quebraria a string), então o toggle busca a note em _permScopes."""
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert "_grantFilesRead" in app_js and "_permScopes" in app_js
    # o grant de files.read manda a note (pasta) no corpo
    assert "scope:'files.read', note:" in app_js
    # ramo específico do files.read no toggle (pede a pasta em vez de grant seco)
    assert "scope === 'files.read'" in app_js


def test_painel_de_auditoria_esta_ligado():
    """Épico 1.3 — o painel 'Atividade (24h)' precisa do botão no HTML e das
    funções de abertura/carregamento no JS."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openAudit()"' in html
    assert 'id="audit-overlay"' in html
    for fn in ("function openAudit", "function loadAudit", "/api/audit"):
        assert fn in app_js


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
