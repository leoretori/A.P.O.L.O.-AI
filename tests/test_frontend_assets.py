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


def test_painel_de_auditoria_esta_ligado():
    """Épico 1.3 — o painel 'Atividade (24h)' precisa do botão no HTML e das
    funções de abertura/carregamento no JS."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    app_js = (STATIC / "js" / "app.js").read_text(encoding="utf-8")
    assert 'onclick="openAudit()"' in html
    assert 'id="audit-overlay"' in html
    for fn in ("function openAudit", "function loadAudit", "/api/audit"):
        assert fn in app_js


def test_js_css_tem_cache_control_no_cache():
    """StaticFiles manda ETag mas não Cache-Control → navegador cacheia por
    heurística e serve código velho após update. O middleware força `no-cache`
    (revalida via ETag, barato) no JS/CSS do app — garante UI fresca."""
    for path in ("/js/app.js", "/css/app.css", "/js/enhancements.js"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers.get("cache-control") == "no-cache", path


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
