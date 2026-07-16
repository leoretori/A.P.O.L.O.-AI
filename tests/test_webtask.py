"""Automação de tarefas web em sandbox (M10, Épico 10.3).

Trava o núcleo determinístico: allowlist de domínios (sandbox), validação da
receita, execução contra driver FAKE (sem rede), seguir link, e o parser de HTML.
A sandbox é reforçada tanto na validação quanto EM TEMPO DE EXECUÇÃO.
"""

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


def test_run_bloqueia_redirect_para_fora_da_sandbox():
    """Achado da auditoria de segurança 2026-07-15: um driver que segue
    redirect (30x) pode devolver uma página de um host DIFERENTE do pedido —
    a URL inicial batia na allowlist, mas o destino final não. `run()` tinha
    que reconferir o destino, não só a URL pedida."""
    class RedirectDriver:
        def open(self, url):
            # pediu example.com, mas o "servidor" redirecionou pra fora
            return {"url": "https://evil.com/roubado", "title": "x",
                   "text": "y", "links": []}

    steps = [{"op": "open", "url": "https://example.com"}]
    r = W.run(steps, RedirectDriver(), ["example.com"])
    assert r["ok"] is False and "fora da sandbox" in r["error"]
    assert r["visited"] == []   # nunca contou como visitado


# ── HttpDriver: redirects não escapam a sandbox (2026-07-15) ────
class _FakeResp:
    def __init__(self, url, redirect_to=None):
        self.url = url
        self.is_redirect = redirect_to is not None
        self.text = "<html><title>T</title><body>conteudo bem longo o suficiente aqui</body></html>"
        if redirect_to:
            self.next_request = type("Req", (), {"url": redirect_to})()

    def raise_for_status(self):
        pass


class _FakeHttpxClient:
    def __init__(self, *a, **kw):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def get(self, url):
        self.calls.append(url)
        if url == "https://example.com/start":
            return _FakeResp(url, redirect_to="https://evil.com/final")
        return _FakeResp(url)


def test_httpdriver_bloqueia_redirect_para_fora_da_allowlist(monkeypatch):
    monkeypatch.setattr("httpx.Client", _FakeHttpxClient)
    driver = W.HttpDriver(allowed=["example.com"])
    try:
        driver.open("https://example.com/start")
        assert False, "deveria ter levantado ValueError"
    except ValueError as e:
        assert "bloqueado" in str(e) and "evil.com" in str(e)


def test_httpdriver_redirect_dentro_da_allowlist_segue_normal(monkeypatch):
    class _OkClient(_FakeHttpxClient):
        def get(self, url):
            self.calls.append(url)
            if url == "https://example.com/start":
                return _FakeResp(url, redirect_to="https://example.com/final")
            return _FakeResp(url)

    monkeypatch.setattr("httpx.Client", _OkClient)
    driver = W.HttpDriver(allowed=["example.com"])
    page = driver.open("https://example.com/start")
    assert page["url"] == "https://example.com/final"


def test_httpdriver_sem_allowed_segue_redirects_livremente(monkeypatch):
    """Sem `allowed` (uso fora do webtask), comportamento antigo preservado:
    segue redirect via follow_redirects=True, sem checagem de sandbox."""
    calls = []

    class _LegacyClient:
        def __init__(self, *a, **kw):
            calls.append(kw.get("follow_redirects"))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def get(self, url):
            return _FakeResp("https://anywhere.example/final")

    monkeypatch.setattr("httpx.Client", _LegacyClient)
    page = W.HttpDriver().open("https://example.com/start")
    assert calls == [True]
    assert page["url"] == "https://anywhere.example/final"


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
