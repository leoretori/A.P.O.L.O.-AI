"""fetch_page_text() é o coração dos fetchers do aprendizado.

Regressão real (commit 2200f13, "perf: 7 melhorias de desempenho"): a troca do
httpx.AsyncClient por-request pelo pool persistente removeu a linha
`headers = {...}`, deixando `client.get(url, headers=headers)` apontando para um
nome indefinido. TODO fetch não-Wikipédia passou a levantar NameError — engolido
pelo `except ... logger.debug` — e o pipeline ficou em `buscados:0` (não aprendia
nada). Estes testes travam esse contrato: um fetch comum extrai texto e NÃO
levanta NameError.
"""
import asyncio


import src.web_search as ws


class _FakeResp:
    def __init__(self, text="", status=200, json_payload=None):
        self.text = text
        self.status_code = status
        self._json = json_payload or {}

    def json(self):
        return self._json


class _FakeClient:
    """Registra a última chamada .get e devolve uma resposta pré-fabricada."""
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": headers})
        return self._resp


def test_fetch_pagina_comum_extrai_texto_sem_nameerror(monkeypatch):
    html = (
        "<html><body>"
        "<script>ignore()</script>"
        "<p>" + ("Este é um parágrafo de conteúdo real bem longo. " * 3) + "</p>"
        "<nav>menu que deve sumir</nav>"
        "</body></html>"
    )
    fake = _FakeClient(_FakeResp(text=html, status=200))
    monkeypatch.setattr(ws, "_get_http_client", lambda: fake)

    out = asyncio.run(ws.fetch_page_text("https://exemplo.com/artigo"))

    # O bug fazia isto retornar "" (NameError engolido). Agora extrai o texto.
    assert "parágrafo de conteúdo real" in out
    assert "menu que deve sumir" not in out          # <nav> removido
    assert len(fake.calls) == 1 and fake.calls[0]["url"] == "https://exemplo.com/artigo"


def test_fetch_wikipedia_usa_a_api_oficial(monkeypatch):
    payload = {"query": {"pages": {"42": {"extract": "Texto limpo da Wikipédia."}}}}
    fake = _FakeClient(_FakeResp(status=200, json_payload=payload))
    monkeypatch.setattr(ws, "_get_http_client", lambda: fake)

    out = asyncio.run(ws.fetch_page_text("https://pt.wikipedia.org/wiki/Via_L%C3%A1ctea"))

    assert out == "Texto limpo da Wikipédia."
    # bateu na API (w/api.php), não no HTML cru
    assert "/w/api.php" in fake.calls[0]["url"]


def test_fetch_status_nao_200_retorna_vazio(monkeypatch):
    fake = _FakeClient(_FakeResp(text="erro", status=404))
    monkeypatch.setattr(ws, "_get_http_client", lambda: fake)
    assert asyncio.run(ws.fetch_page_text("https://exemplo.com/nao-existe")) == ""
