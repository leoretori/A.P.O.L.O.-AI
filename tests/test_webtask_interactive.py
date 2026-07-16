"""Navegador interativo em sandbox (M20.1): click/fill/submit com preview de
cada passo e o gate de efeito ('nunca um clique cego')."""

from src.webtask import (
    SECRET_ENV_PREFIX,
    describe_step,
    is_effect,
    preview_interactive,
    run_interactive,
    validate_interactive,
)

ALLOWED = ["example.com"]


class FakeInteractiveDriver:
    """Simula um navegador: guarda o que foi preenchido/clicado/enviado."""
    def __init__(self, submit_url="https://example.com/ok"):
        self.filled = {}
        self.clicks = []
        self.submitted = False
        self._submit_url = submit_url
        self._url = "https://example.com/form"

    def _page(self, url=None):
        return {"url": url or self._url, "title": "Form", "text": "corpo", "links": []}

    def open(self, url):
        self._url = url
        return self._page(url)

    def click(self, selector=None, contains=None):
        self.clicks.append(selector or contains)
        return self._page()

    def fill(self, selector, value):
        self.filled[selector] = value
        return self._page()

    def submit(self, selector=None):
        self.submitted = True
        return self._page(self._submit_url)


def _recipe(effect=True):
    steps = [
        {"op": "open", "url": "https://example.com/form"},
        {"op": "fill", "selector": "input[name=q]", "value": "oi"},
    ]
    if effect:
        steps.append({"op": "submit", "selector": "button"})
    steps.append({"op": "extract", "what": "title"})
    return steps


def test_is_effect_e_describe():
    assert is_effect({"op": "submit"}) is True
    assert is_effect({"op": "click", "effect": True}) is True
    assert is_effect({"op": "fill", "selector": "x", "value": "y"}) is False
    assert "enviar o formulário" in describe_step({"op": "submit"})
    assert "preencher" in describe_step({"op": "fill", "selector": "a", "value": "b"})


def test_validate_interativo_click_sem_alvo():
    errs = validate_interactive(
        [{"op": "open", "url": "https://example.com"}, {"op": "click"}], ALLOWED)
    assert any("click" in e for e in errs)


def test_validate_interativo_fill_exige_selector_e_value():
    errs = validate_interactive(
        [{"op": "open", "url": "https://example.com"}, {"op": "fill"}], ALLOWED)
    assert any("selector" in e for e in errs) and any("value" in e for e in errs)


def test_preview_lista_cada_passo_e_destaca_efeitos():
    pv = preview_interactive(_recipe(), ALLOWED)
    assert pv["ok"] and len(pv["plan"]) == 4
    assert [p["op"] for p in pv["plan"]] == ["open", "fill", "submit", "extract"]
    assert len(pv["effects"]) == 1 and pv["effects"][0]["op"] == "submit"


def test_run_para_em_efeito_nao_confirmado():
    d = FakeInteractiveDriver()
    out = run_interactive(_recipe(), d, ALLOWED)          # sem confirm_effects
    assert out["ok"] is False and out["status"] == "needs_confirmation"
    assert out["effects"][0]["op"] == "submit"
    assert d.submitted is False                            # NÃO submeteu no escuro


def test_run_confirmado_executa_e_registra_na_trilha():
    d = FakeInteractiveDriver()
    out = run_interactive(_recipe(), d, ALLOWED, confirm_effects=True)
    assert out["ok"] is True
    assert d.filled == {"input[name=q]": "oi"} and d.submitted is True
    # o efeito entra na trilha auditável (ledger)
    assert len(out["ledger"]) == 1 and out["ledger"][0]["op"] == "submit"
    # a extração pós-submit funciona
    assert out["results"][0]["what"] == "title"


def test_receita_sem_efeito_roda_sem_confirmacao():
    d = FakeInteractiveDriver()
    out = run_interactive(_recipe(effect=False), d, ALLOWED)
    assert out["ok"] is True and out["ledger"] == []
    assert d.filled == {"input[name=q]": "oi"} and d.submitted is False


def test_submit_para_fora_da_sandbox_e_bloqueado():
    d = FakeInteractiveDriver(submit_url="https://evil.com/steal")
    out = run_interactive(_recipe(), d, ALLOWED, confirm_effects=True)
    assert out["ok"] is False and "sandbox" in out["error"]


def test_open_com_redirect_para_fora_da_sandbox_e_bloqueado():
    """Achado da auditoria de segurança 2026-07-15: o passo 'open' não
    reconferia o destino após a navegação — só a URL pedida antes de abrir."""
    class RedirectDriver:
        def open(self, url):
            return {"url": "https://evil.com/roubado", "title": "x", "text": "y", "links": []}

    steps = [{"op": "open", "url": "https://example.com"}]
    out = run_interactive(steps, RedirectDriver(), ALLOWED, confirm_effects=True)
    assert out["ok"] is False and "sandbox" in out["error"]
    assert out["visited"] == []


# ───────────────── M20.3 login seguro: segredos, nunca em texto puro ─────────
def _login_recipe():
    return [
        {"op": "open", "url": "https://example.com/login"},
        {"op": "fill", "selector": "#user", "value": "leo"},
        {"op": "fill", "selector": "#pass", "secret": "MINHA_SENHA"},
    ]


def test_fill_aceita_secret_no_lugar_de_value():
    errs = validate_interactive(_login_recipe(), ALLOWED)
    assert errs == []


def test_secret_e_redigido_na_previa_e_no_traco(monkeypatch):
    monkeypatch.setenv(SECRET_ENV_PREFIX + "MINHA_SENHA", "s3nh4-secreta")
    d = FakeInteractiveDriver()
    out = run_interactive(_login_recipe(), d, ALLOWED)
    # o valor REAL foi preenchido no campo...
    assert d.filled["#pass"] == "s3nh4-secreta"
    # ...mas NUNCA aparece na prévia nem no traço (redigido)
    step = {"op": "fill", "selector": "#pass", "secret": "MINHA_SENHA"}
    assert "s3nh4-secreta" not in describe_step(step) and "•••" in describe_step(step)
    assert all("s3nh4-secreta" not in t["detail"] for t in out["trace"])


def test_secret_ausente_falha_claro(monkeypatch):
    monkeypatch.delenv(SECRET_ENV_PREFIX + "MINHA_SENHA", raising=False)
    out = run_interactive(_login_recipe(), FakeInteractiveDriver(), ALLOWED)
    assert out["ok"] is False and "MINHA_SENHA" in out["error"]
