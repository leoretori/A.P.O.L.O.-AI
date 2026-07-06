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
