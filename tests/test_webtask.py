"""Automação de tarefas web em sandbox (M10, Épico 10.3).

Trava o núcleo determinístico: allowlist de domínios (sandbox), validação da
receita, execução contra driver FAKE (sem rede), seguir link, e o parser de HTML.
A sandbox é reforçada tanto na validação quanto EM TEMPO DE EXECUÇÃO.
"""
import pytest

from src import webtask as W


# ── sandbox de domínios ─────────────────────────────────────────
def test_parse_domains_normaliza():
    d = W.parse_domains("https://www.Example.com/foo, docs.python.org\n; example.com")
    assert d == ["example.com", "docs.python.org"]   # sem www, sem esquema, sem dup


def test_domain_allowed_inclui_subdominio():
    assert W.domain_allowed("https://docs.python.org/3/", ["python.org"]) is True
    assert W.domain_allowed("https://python.org", ["python.org"]) is True
    assert W.domain_allowed("https://evil.com", ["python.org"]) is False


# ── validação ───────────────────────────────────────────────────
def test_validate_ok():
    steps = [{"op": "open", "url": "https://example.com"}, {"op": "extract", "what": "title"}]
    assert W.validate(steps, ["example.com"]) == []


def test_validate_primeiro_passo_precisa_ser_open():
    assert any("1º passo" in e for e in
               W.validate([{"op": "extract", "what": "text"}], ["example.com"]))


def test_validate_bloqueia_dominio_fora_da_allowlist():
    steps = [{"op": "open", "url": "https://evil.com"}]
    assert any("fora da allowlist" in e for e in W.validate(steps, ["example.com"]))


def test_validate_op_desconhecida_e_sem_dominios():
    errs = W.validate([{"op": "hack"}], [])
    assert any("desconhecida" in e for e in errs)
    assert any("nenhum domínio" in e for e in errs)


def test_validate_extract_what_invalido():
    steps = [{"op": "open", "url": "https://example.com"}, {"op": "extract", "what": "cookies"}]
    assert any("what inválido" in e for e in W.validate(steps, ["example.com"]))


# ── execução com driver fake ────────────────────────────────────
class FakeDriver:
    def __init__(self, pages):
        self.pages = pages
        self.opened = []

    def open(self, url):
        self.opened.append(url)
        return self.pages[url]


def _pages():
    return {
        "https://example.com": {"url": "https://example.com", "title": "Início",
                                "text": "conteúdo da home " * 5,
                                "links": [{"text": "Notícias de hoje", "url": "https://example.com/news"}]},
        "https://example.com/news": {"url": "https://example.com/news", "title": "Notícias",
                                     "text": "manchete importante " * 5, "links": []},
    }


def test_run_extrai_titulo_e_texto():
    steps = [{"op": "open", "url": "https://example.com"},
             {"op": "extract", "what": "title"}, {"op": "extract", "what": "text"}]
    r = W.run(steps, FakeDriver(_pages()), ["example.com"])
    assert r["ok"] and len(r["results"]) == 2
    assert r["results"][0]["value"] == "Início"
    assert r["visited"] == ["https://example.com"]


def test_run_segue_link_por_texto():
    steps = [{"op": "open", "url": "https://example.com"},
             {"op": "follow", "contains": "notícias"},   # case-insensitive
             {"op": "extract", "what": "title"}]
    r = W.run(steps, FakeDriver(_pages()), ["example.com"])
    assert r["ok"] and r["results"][0]["value"] == "Notícias"
    assert r["visited"] == ["https://example.com", "https://example.com/news"]


def test_run_follow_link_inexistente_falha_limpo():
    steps = [{"op": "open", "url": "https://example.com"},
             {"op": "follow", "contains": "inexistente"}]
    r = W.run(steps, FakeDriver(_pages()), ["example.com"])
    assert r["ok"] is False and "não encontrado" in r["error"]


def test_run_bloqueia_link_fora_da_sandbox_em_runtime():
    pages = _pages()
    pages["https://example.com"]["links"] = [{"text": "sair", "url": "https://evil.com/x"}]
    steps = [{"op": "open", "url": "https://example.com"}, {"op": "follow", "contains": "sair"}]
    r = W.run(steps, FakeDriver(pages), ["example.com"])
    assert r["ok"] is False and "fora da sandbox" in r["error"]


def test_run_rejeita_receita_invalida_antes_de_navegar():
    drv = FakeDriver(_pages())
    r = W.run([{"op": "open", "url": "https://evil.com"}], drv, ["example.com"])
    assert r["ok"] is False and drv.opened == []      # nem abriu


# ── parser de HTML ──────────────────────────────────────────────
def test_parse_page_extrai_titulo_texto_e_links_absolutos():
    html = """<html><head><title> Minha Página </title></head><body>
      <nav>menu que deve sumir</nav>
      <p>Este é um parágrafo com bastante conteúdo relevante para extrair.</p>
      <a href="/sobre">Sobre nós</a><script>ignore()</script></body></html>"""
    page = W.parse_page(html, "https://site.com/home")
    assert page["title"] == "Minha Página"
    assert "parágrafo com bastante conteúdo" in page["text"]
    assert "menu que deve sumir" not in page["text"]      # nav removido
    assert page["links"] == [{"text": "Sobre nós", "url": "https://site.com/sobre"}]
