"""Busca na web via DuckDuckGo + extração de conteúdo de páginas."""

import asyncio
import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 2500
FETCH_TIMEOUT = 8

# #5 Pool HTTP persistente — reutiliza conexões TCP em vez de abrir/fechar a cada fetch.
# Keep-alive reduz ~80ms de latência de TCP handshake por requisição para hosts repetidos.
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=FETCH_TIMEOUT,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5,
                                keepalive_expiry=30),
            headers={"User-Agent": "Mozilla/5.0 (compatible; ApoloAI/1.0; research)"},
        )
    return _http_client


def _ddg_search_sync(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r["title"], "url": r["href"], "snippet": r.get("body", "")}
            for r in results
        ]
    except Exception as e:
        logger.warning(f"DuckDuckGo error: {e}")
        return []


async def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Retorna [{title, url, snippet}] do DuckDuckGo (executa em thread para não bloquear)."""
    return await asyncio.to_thread(_ddg_search_sync, query, max_results)


def _wikipedia_api(url: str) -> str | None:
    """Se a URL for um artigo da Wikipédia, devolve a URL da API de extração de texto
    (a Wikipédia bloqueia scraping de HTML com 403; a API serve o texto limpo)."""
    from urllib.parse import urlparse, unquote, quote
    try:
        p = urlparse(url)
        if "wikipedia.org" in p.netloc and "/wiki/" in p.path:
            title = unquote(p.path.split("/wiki/", 1)[1])
            return (
                f"{p.scheme}://{p.netloc}/w/api.php?action=query&prop=extracts"
                f"&explaintext=1&format=json&redirects=1&titles={quote(title)}"
            )
    except Exception:
        pass
    return None


def _extract_wikipedia_text(payload: dict) -> str:
    try:
        for _, page in payload.get("query", {}).get("pages", {}).items():
            if page.get("extract"):
                return page["extract"]
    except Exception:
        pass
    return ""


async def fetch_page_text(url: str) -> str:
    """Baixa página e extrai texto principal (sem scripts/nav/footer).
    Wikipédia é tratada via API oficial (o HTML retorna 403 para bots)."""
    try:
        client = _get_http_client()
        if True:  # mantém indentação do bloco original sem quebrar lógica
            wiki_api = _wikipedia_api(url)
            if wiki_api:
                # A Wikimedia exige User-Agent com URL/contato (senão 403 por política de bots).
                resp = await client.get(wiki_api, headers={
                    "User-Agent": "ApoloAI/1.0 (https://github.com/apolo-ai; autonomous learning agent)",
                    "Accept": "application/json",
                })
                if resp.status_code != 200:
                    return ""
                return _extract_wikipedia_text(resp.json())[:MAX_CONTENT_CHARS]

            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return ""
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
                tag.decompose()
            lines = [
                l.strip()
                for l in soup.get_text(separator="\n").splitlines()
                if len(l.strip()) > 40
            ]
            return "\n".join(lines)[:MAX_CONTENT_CHARS]
    except Exception as e:
        logger.debug(f"Fetch failed {url}: {e}")
        return ""


async def web_research(query: str, max_results: int = 2) -> tuple[str, list[dict]]:
    """
    Pesquisa na web e retorna (contexto_formatado, lista_de_fontes).
    Busca snippets primeiro e faz fetch completo das top 2 páginas.
    """
    results = await search_web(query, max_results=max_results + 1)
    if not results:
        return "", []

    top = results[:max_results]
    fetch_tasks = [fetch_page_text(r["url"]) for r in top]
    try:
        contents = await asyncio.wait_for(
            asyncio.gather(*fetch_tasks, return_exceptions=True),
            timeout=12.0,
        )
    except asyncio.TimeoutError:
        contents = [r.get("snippet", "") for r in top]

    parts = []
    sources = []
    for r, content in zip(top, contents):
        text = content if isinstance(content, str) and content else r.get("snippet", "")
        if not text:
            continue
        parts.append(f"**{r['title']}**\nURL: {r['url']}\n{text}")
        # Inclui um trecho na fonte → permite reranquear/citar com conteúdo.
        sources.append({"title": r["title"], "url": r["url"], "snippet": text[:400]})

    return "\n\n---\n\n".join(parts), sources
