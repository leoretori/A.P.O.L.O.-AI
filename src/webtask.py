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
                link = next((l for l in page.get("links", [])
                             if sub in (l.get("text", "").lower())), None)
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
