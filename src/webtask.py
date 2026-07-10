"""Automação de tarefas web em sandbox (M10, Épico 10.3).

"Controle de navegador" para tarefas REPETITIVAS, feito à maneira soberana do
projeto: uma RECEITA de passos (abrir → extrair → seguir link) que roda contra um
DRIVER injetável. O driver embutido usa só o que já temos (httpx + BeautifulSoup)
— nada de browser pesado, roda no CPU. Um driver interativo real (Playwright, com
clique/digitação em sites JS) é 🔒 opt-in e fica de fora do padrão soberano.

Duas travas de segurança, no mesmo espírito do M6:
  • OPT-IN por escopo `browser.control` (nada roda sem consentimento);
  • SANDBOX por allowlist de DOMÍNIOS (a `note` do grant) — toda navegação, e cada
    link seguido, é checada contra a allowlist (defesa em profundidade).
As receitas são READ-ONLY (só GET) → não modificam o mundo (sem necessidade de
undo); cada passo é auditável. Núcleo DETERMINÍSTICO: `validate`/`run` com driver
injetável (fake nos testes).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("apolo.webtask")

OPS = ("open", "extract", "follow")
EXTRACT_WHAT = ("title", "text", "links")
MAX_STEPS = 20
MAX_NAV = 10                     # navegações (open+follow) por receita — anti-loop
MAX_TEXT_CHARS = 4000


def parse_domains(note: str) -> list[str]:
    """A note do grant vira a allowlist de domínios (separados por vírgula/linha/;).
    Normaliza para host minúsculo sem 'www.' nem esquema."""
    out: list[str] = []
    for raw in (note or "").replace(";", "\n").replace(",", "\n").splitlines():
        d = raw.strip().lower()
        if not d:
            continue
        if "://" in d:
            d = urlparse(d).netloc or d
        d = d.split("/")[0]
        if d.startswith("www."):
            d = d[4:]
        if d and d not in out:
            out.append(d)
    return out


def domain_of(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


def domain_allowed(url: str, allowed: list[str]) -> bool:
    """True se o host da URL é (ou é subdomínio de) algum domínio da allowlist."""
    host = domain_of(url)
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed)


def validate(steps: list[dict], allowed: list[str]) -> list[str]:
    """Confere a receita SEM executá-la. Devolve a lista de erros (vazia = ok)."""
    errors: list[str] = []
    if not steps:
        return ["receita vazia"]
    if len(steps) > MAX_STEPS:
        errors.append(f"receita longa demais (máx {MAX_STEPS} passos)")
    if not allowed:
        errors.append("nenhum domínio autorizado — autorize 'browser.control' e informe os domínios")
    if steps and steps[0].get("op") != "open":
        errors.append("o 1º passo precisa ser 'open' (abrir uma página)")
    navs = 0
    for i, st in enumerate(steps):
        op = st.get("op")
        if op not in OPS:
            errors.append(f"passo {i + 1}: operação desconhecida '{op}'")
            continue
        if op == "open":
            navs += 1
            url = st.get("url", "")
            if not url:
                errors.append(f"passo {i + 1}: 'open' sem url")
            elif allowed and not domain_allowed(url, allowed):
                errors.append(f"passo {i + 1}: domínio de '{url}' fora da allowlist")
        elif op == "follow":
            navs += 1
            if not st.get("contains"):
                errors.append(f"passo {i + 1}: 'follow' precisa de 'contains' (texto do link)")
        elif op == "extract":
            if st.get("what", "text") not in EXTRACT_WHAT:
                errors.append(f"passo {i + 1}: 'extract' what inválido (use {'/'.join(EXTRACT_WHAT)})")
    if navs > MAX_NAV:
        errors.append(f"navegações demais (máx {MAX_NAV})")
    return errors


def run(steps: list[dict], driver, allowed: list[str], on_step=None) -> dict:
    """Executa a receita contra `driver` (injetável). driver.open(url) -> page dict
    {url, title, text, links:[{text,url}]}. Reforça a sandbox em CADA navegação.
    Read-only: nada é modificado. Devolve {ok, results, trace, visited, error?}."""
    errors = validate(steps, allowed)
    if errors:
        return {"ok": False, "error": "; ".join(errors), "results": [], "trace": [], "visited": []}

    results: list[dict] = []
    trace: list[dict] = []
    visited: list[str] = []
    page: dict | None = None

    def _record(op: str, detail: str, ok: bool = True):
        entry = {"op": op, "detail": detail, "ok": ok}
        trace.append(entry)
        if on_step:
            try:
                on_step(entry)
            except Exception:
                pass

    try:
        for st in steps:
            op = st.get("op")
            if op == "open":
                url = st["url"]
                if not domain_allowed(url, allowed):
                    _record("open", f"bloqueado (fora da sandbox): {url}", ok=False)
                    return {"ok": False, "error": f"navegação bloqueada: {url}",
                            "results": results, "trace": trace, "visited": visited}
                page = driver.open(url)
                visited.append(page.get("url", url))
                _record("open", page.get("url", url))
            elif op == "follow":
                if not page:
                    return {"ok": False, "error": "'follow' sem página aberta",
                            "results": results, "trace": trace, "visited": visited}
                sub = (st.get("contains") or "").lower()
                link = next((lnk for lnk in page.get("links", [])
                             if sub in (lnk.get("text", "").lower())), None)
                if not link:
                    _record("follow", f"nenhum link com '{sub}'", ok=False)
                    return {"ok": False, "error": f"link não encontrado: '{sub}'",
                            "results": results, "trace": trace, "visited": visited}
                if not domain_allowed(link["url"], allowed):
                    _record("follow", f"bloqueado (fora da sandbox): {link['url']}", ok=False)
                    return {"ok": False, "error": f"link fora da sandbox: {link['url']}",
                            "results": results, "trace": trace, "visited": visited}
                page = driver.open(link["url"])
                visited.append(page.get("url", link["url"]))
                _record("follow", page.get("url", link["url"]))
            elif op == "extract":
                if not page:
                    return {"ok": False, "error": "'extract' sem página aberta",
                            "results": results, "trace": trace, "visited": visited}
                what = st.get("what", "text")
                if what == "title":
                    value = page.get("title", "")
                elif what == "links":
                    lim = int(st.get("limit", 30))
                    value = page.get("links", [])[:lim]
                else:
                    value = (page.get("text", "") or "")[:MAX_TEXT_CHARS]
                results.append({"what": what, "value": value, "from": page.get("url", "")})
                _record("extract", f"{what} de {page.get('url', '')}")
    except Exception as e:
        return {"ok": False, "error": str(e)[:300],
                "results": results, "trace": trace, "visited": visited}

    return {"ok": True, "results": results, "trace": trace, "visited": visited}


# ── Parser + driver embutido (soberano: httpx + BeautifulSoup, sem browser) ──

def parse_page(html: str, base_url: str) -> dict:
    """HTML → {url, title, text, links}. Determinístico; links absolutizados."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    title = (soup.title.get_text().strip() if soup.title else "")
    links: list[dict] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        if href.startswith(("http://", "https://")) and href not in seen:
            seen.add(href)
            links.append({"text": " ".join(a.get_text().split())[:120], "url": href})
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
        tag.decompose()
    text = "\n".join(l.strip() for l in soup.get_text(separator="\n").splitlines()
                     if len(l.strip()) > 20)
    return {"url": base_url, "title": title, "text": text, "links": links}


class HttpDriver:
    """Driver embutido read-only: baixa a página via httpx e parseia. Soberano
    (sem navegador). Para sites que exigem JS/clique, use um driver interativo
    (🔒 opt-in). Síncrono de propósito — o router o chama via to_thread."""
    def __init__(self, timeout: float = 8.0):
        self._timeout = timeout

    def open(self, url: str) -> dict:
        import httpx
        with httpx.Client(timeout=self._timeout, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; ApoloAI/1.0; automation)"}) as c:
            resp = c.get(url)
            resp.raise_for_status()
            return parse_page(resp.text, str(resp.url))


EXAMPLE_RECIPE = [
    {"op": "open", "url": "https://example.com"},
    {"op": "extract", "what": "title"},
    {"op": "extract", "what": "text"},
]


# ─────────────────────────────────────────────────────────────────────────
# Modo INTERATIVO (M20, Épico 20.1) — sobe a automação de read-only para
# clique/preenchimento. Um driver interativo real (Playwright) é 🔒 opt-in e
# fica atrás do escopo `browser.interact`; o núcleo (validate/preview/run)
# segue determinístico e testável com um driver fake.
#
# Segurança reforçada (20.1 + 20.2): mesma sandbox de domínios; PREVIEW de cada
# passo; e a fronteira do EFEITO (submeter formulário) NUNCA roda num clique
# cego — exige confirmação explícita e entra numa TRILHA auditável.
# ─────────────────────────────────────────────────────────────────────────

INTERACT_OPS = OPS + ("click", "fill", "submit")
EFFECT_OPS = ("submit",)          # muda o mundo → confirmação + trilha (20.2)


def is_effect(step: dict) -> bool:
    """O passo tem efeito no mundo (submete/altera)? `effect: true` força."""
    return step.get("op") in EFFECT_OPS or bool(step.get("effect"))


# Segredos (M20.3): logins não ficam em texto puro na receita. Um passo
# `fill` pode trazer `secret: "NOME"` em vez de `value`; o valor é resolvido de
# `APOLO_WEB_SECRET_<NOME>` na hora de rodar e é REDIGIDO em prévia/trilha/traço.
SECRET_ENV_PREFIX = "APOLO_WEB_SECRET_"
_REDACTED = "•••"


def resolve_secret(name: str) -> str | None:
    """Valor do segredo pelo ambiente (soberano, sem texto puro no banco)."""
    import os
    return os.environ.get(SECRET_ENV_PREFIX + (name or "").strip().upper())


def describe_step(step: dict) -> str:
    """Frase legível do que o passo FARÁ — a base do 'preview de cada passo'."""
    op = step.get("op")
    if op == "open":
        return f"abrir {step.get('url', '')}"
    if op == "follow":
        return f"seguir o link com “{step.get('contains', '')}”"
    if op == "extract":
        return f"extrair {step.get('what', 'text')} da página"
    if op == "click":
        return f"clicar em {step.get('selector') or '“' + step.get('contains', '') + '”'}"
    if op == "fill":
        if step.get("secret"):
            return f"preencher {step.get('selector', '')} com {_REDACTED} (segredo {step['secret']})"
        return f"preencher {step.get('selector', '')} com “{step.get('value', '')}”"
    if op == "submit":
        alvo = step.get('selector')
        return "enviar o formulário" + (f" ({alvo})" if alvo else " atual")
    return f"operação '{op}'"


def validate_interactive(steps: list[dict], allowed: list[str]) -> list[str]:
    """Valida uma receita interativa SEM executá-la (inclui click/fill/submit)."""
    errors: list[str] = []
    if not steps:
        return ["receita vazia"]
    if len(steps) > MAX_STEPS:
        errors.append(f"receita longa demais (máx {MAX_STEPS} passos)")
    if not allowed:
        errors.append("nenhum domínio autorizado — autorize 'browser.interact' e informe os domínios")
    if steps and steps[0].get("op") != "open":
        errors.append("o 1º passo precisa ser 'open' (abrir uma página)")
    navs = 0
    for i, st in enumerate(steps):
        op = st.get("op")
        if op not in INTERACT_OPS:
            errors.append(f"passo {i + 1}: operação desconhecida '{op}'")
            continue
        if op == "open":
            navs += 1
            url = st.get("url", "")
            if not url:
                errors.append(f"passo {i + 1}: 'open' sem url")
            elif allowed and not domain_allowed(url, allowed):
                errors.append(f"passo {i + 1}: domínio de '{url}' fora da allowlist")
        elif op == "follow":
            navs += 1
            if not st.get("contains"):
                errors.append(f"passo {i + 1}: 'follow' precisa de 'contains' (texto do link)")
        elif op == "extract":
            if st.get("what", "text") not in EXTRACT_WHAT:
                errors.append(f"passo {i + 1}: 'extract' what inválido (use {'/'.join(EXTRACT_WHAT)})")
        elif op == "click":
            if not (st.get("selector") or st.get("contains")):
                errors.append(f"passo {i + 1}: 'click' precisa de 'selector' ou 'contains'")
        elif op == "fill":
            if not st.get("selector"):
                errors.append(f"passo {i + 1}: 'fill' precisa de 'selector'")
            if "value" not in st and not st.get("secret"):
                errors.append(f"passo {i + 1}: 'fill' precisa de 'value' ou 'secret'")
        # 'submit' não tem args obrigatórios (form atual ou por selector)
    if navs > MAX_NAV:
        errors.append(f"navegações demais (máx {MAX_NAV})")
    return errors


def preview_interactive(steps: list[dict], allowed: list[str]) -> dict:
    """Prévia de CADA passo (20.1) + os passos com EFEITO destacados (20.2),
    SEM navegar. É o que o front mostra antes de deixar rodar."""
    errors = validate_interactive(steps, allowed)
    plan = [{"index": i, "op": st.get("op"), "detail": describe_step(st),
             "effect": is_effect(st)} for i, st in enumerate(steps)]
    return {"ok": not errors, "errors": errors, "plan": plan,
            "effects": [p for p in plan if p["effect"]]}


def run_interactive(steps: list[dict], driver, allowed: list[str], *,
                    confirm_effects: bool = False, on_step=None) -> dict:
    """Executa a receita interativa contra `driver` (injetável). Reforça a
    sandbox em cada navegação e NUNCA roda um passo de efeito sem
    `confirm_effects=True` — se houver efeito não confirmado, para e devolve
    `status:'needs_confirmation'` com os passos que mudariam o mundo. Cada
    efeito aplicado entra em `ledger` (a trilha auditável do 20.2).

    driver expõe: open(url), click(selector=?, contains=?), fill(selector,value),
    submit(selector=?) → cada um devolve a page dict resultante.
    """
    errors = validate_interactive(steps, allowed)
    if errors:
        return {"ok": False, "error": "; ".join(errors), "results": [],
                "trace": [], "visited": [], "ledger": []}

    effects = [i for i, st in enumerate(steps) if is_effect(st)]
    if effects and not confirm_effects:
        return {"ok": False, "status": "needs_confirmation",
                "error": "esta receita tem passos que mudam o mundo — confirme antes",
                "effects": [{"index": i, "op": steps[i].get("op"),
                             "detail": describe_step(steps[i])} for i in effects],
                "results": [], "trace": [], "visited": [], "ledger": []}

    results: list[dict] = []
    trace: list[dict] = []
    visited: list[str] = []
    ledger: list[dict] = []
    page: dict | None = None

    def _record(op: str, detail: str, ok: bool = True, effect: bool = False):
        entry = {"op": op, "detail": detail, "ok": ok, "effect": effect}
        trace.append(entry)
        if effect and ok:
            ledger.append(entry)
        if on_step:
            try:
                on_step(entry)
            except Exception:
                pass

    def _guard(url: str, op: str) -> dict | None:
        if not domain_allowed(url, allowed):
            _record(op, f"bloqueado (fora da sandbox): {url}", ok=False)
            return {"ok": False, "error": f"navegação bloqueada: {url}",
                    "results": results, "trace": trace, "visited": visited, "ledger": ledger}
        return None

    try:
        for st in steps:
            op = st.get("op")
            if op == "open":
                url = st["url"]
                blocked = _guard(url, "open")
                if blocked:
                    return blocked
                page = driver.open(url)
                visited.append(page.get("url", url))
                _record("open", page.get("url", url))
            elif op == "follow":
                if not page:
                    return {"ok": False, "error": "'follow' sem página aberta",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                sub = (st.get("contains") or "").lower()
                link = next((lnk for lnk in page.get("links", [])
                             if sub in (lnk.get("text", "").lower())), None)
                if not link:
                    _record("follow", f"nenhum link com '{sub}'", ok=False)
                    return {"ok": False, "error": f"link não encontrado: '{sub}'",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                blocked = _guard(link["url"], "follow")
                if blocked:
                    return blocked
                page = driver.open(link["url"])
                visited.append(page.get("url", link["url"]))
                _record("follow", page.get("url", link["url"]))
            elif op == "extract":
                if not page:
                    return {"ok": False, "error": "'extract' sem página aberta",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                what = st.get("what", "text")
                if what == "title":
                    value = page.get("title", "")
                elif what == "links":
                    value = page.get("links", [])[:int(st.get("limit", 30))]
                else:
                    value = (page.get("text", "") or "")[:MAX_TEXT_CHARS]
                results.append({"what": what, "value": value, "from": page.get("url", "")})
                _record("extract", f"{what} de {page.get('url', '')}")
            elif op == "click":
                if not page:
                    return {"ok": False, "error": "'click' sem página aberta",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                page = driver.click(selector=st.get("selector"), contains=st.get("contains"))
                if page.get("url"):
                    visited.append(page["url"])
                    if _guard(page["url"], "click"):
                        return {"ok": False, "error": f"clique levou p/ fora da sandbox: {page['url']}",
                                "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                _record("click", describe_step(st))
            elif op == "fill":
                if not page:
                    return {"ok": False, "error": "'fill' sem página aberta",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                if st.get("secret"):
                    value = resolve_secret(st["secret"])
                    if value is None:
                        _record("fill", f"segredo '{st['secret']}' não definido", ok=False)
                        return {"ok": False,
                                "error": f"segredo '{st['secret']}' ausente — defina "
                                         f"{SECRET_ENV_PREFIX}{st['secret'].upper()} no ambiente",
                                "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                else:
                    value = st.get("value", "")
                page = driver.fill(st["selector"], value)
                _record("fill", describe_step(st))       # describe_step redige o segredo
            elif op == "submit":
                if not page:
                    return {"ok": False, "error": "'submit' sem página aberta",
                            "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                page = driver.submit(selector=st.get("selector"))
                if page.get("url"):
                    visited.append(page["url"])
                    if _guard(page["url"], "submit"):
                        return {"ok": False, "error": f"envio levou p/ fora da sandbox: {page['url']}",
                                "results": results, "trace": trace, "visited": visited, "ledger": ledger}
                _record("submit", describe_step(st), effect=True)
    except Exception as e:
        return {"ok": False, "error": str(e)[:300],
                "results": results, "trace": trace, "visited": visited, "ledger": ledger}

    return {"ok": True, "results": results, "trace": trace,
            "visited": visited, "ledger": ledger}


class PlaywrightDriver:
    """Driver INTERATIVO real (🔒 opt-in) — clica/preenche em sites JS via
    Playwright. Fora do padrão soberano (browser pesado); só é usado quando o
    pacote está instalado e o escopo `browser.interact` foi concedido. Lazy: só
    importa o playwright ao abrir a 1ª página, com erro claro se faltar."""
    def __init__(self, timeout: float = 15.0, headless: bool = True):
        self._timeout = timeout * 1000
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    @staticmethod
    def is_available() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except Exception:
            return False

    def _ensure(self):
        if self._page is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(
                "modo interativo exige o Playwright (🔒 opt-in): "
                "`pip install playwright` + `playwright install chromium`") from e
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(self._timeout)

    def _snapshot(self) -> dict:
        p = self._page
        html = p.content()
        page = parse_page(html, p.url)
        page["url"] = p.url
        return page

    def open(self, url: str) -> dict:
        self._ensure()
        self._page.goto(url)
        return self._snapshot()

    def click(self, selector: str | None = None, contains: str | None = None) -> dict:
        self._ensure()
        if selector:
            self._page.click(selector)
        elif contains:
            self._page.get_by_text(contains).first.click()
        return self._snapshot()

    def fill(self, selector: str, value: str) -> dict:
        self._ensure()
        self._page.fill(selector, value)
        return self._snapshot()

    def submit(self, selector: str | None = None) -> dict:
        self._ensure()
        if selector:
            self._page.click(selector)
        else:
            self._page.keyboard.press("Enter")
        return self._snapshot()

    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        except Exception:
            pass


INTERACTIVE_EXAMPLE = [
    {"op": "open", "url": "https://example.com/busca"},
    {"op": "fill", "selector": "input[name=q]", "value": "apolo ai"},
    {"op": "submit", "selector": "button[type=submit]"},
    {"op": "extract", "what": "title"},
]
