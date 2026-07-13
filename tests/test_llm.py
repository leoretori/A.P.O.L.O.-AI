"""Testes da camada de inferência (src/llm.py) — streaming e caminhos de erro.

Usam um provedor fake injetado, sem depender do Ollama. Garantem que `stream_chat`,
`stream_sync` e `chat_resilient` se comportem (incluindo propagação de erro, retry e
circuit breaker) independentemente do backend.
"""

import asyncio

import pytest

import src.llm as llm
import src.providers as providers
from src.resilience import CircuitOpenError


@pytest.fixture(autouse=True)
def _reset_state():
    """Isola cada teste: zera o breaker do Ollama e o provedor injetado."""
    llm._ollama_breaker._fails = 0
    llm._ollama_breaker.state = "closed"
    yield
    providers.reset_provider()
    llm._ollama_breaker._fails = 0
    llm._ollama_breaker.state = "closed"


class _FakeProvider:
    name = "fake"

    def __init__(self, tokens=None, complete_text="ok", fail_times=0):
        self._tokens = tokens or ["a", "b", "c"]
        self._complete_text = complete_text
        self._fail_times = fail_times
        self.calls = 0

    def complete(self, model, messages, options=None, keep_alive=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ConnectionError("falha transitória")
        return self._complete_text

    def stream(self, model, messages, options=None, keep_alive=None, cancel=None):
        for t in self._tokens:
            if cancel is not None and cancel.is_set():
                break
            yield t

    def list_models(self):
        return ["fake:1"]


def _inject(provider):
    providers._provider = provider


# ── stream_chat (async) ──────────────────────────────────────────
def test_stream_chat_produz_tokens():
    _inject(_FakeProvider(tokens=["Oi", ", ", "mundo"]))

    async def run():
        out = []
        async for tok in llm.stream_chat("m", [{"role": "user", "content": "x"}]):
            out.append(tok)
        return out

    assert "".join(asyncio.run(run())) == "Oi, mundo"


def test_stream_chat_sinaliza_cancel_ao_fechar_gerador():
    """Fechar o gerador (cliente clicou 'parar'/desconectou) tem que sinalizar o
    `cancel` ao worker — é assim que a geração encerra e libera o lock do motor em
    vez de seguir até o teto travando o estudo (bug do 'gerou até 132 mesmo parando')."""
    captured = {}

    class _Cap:
        name = "cap"
        def stream(self, model, messages, options=None, keep_alive=None, cancel=None):
            captured["cancel"] = cancel
            for i in range(1000):
                yield f"t{i}"
        def complete(self, *a, **k):
            return ""
    _inject(_Cap())

    async def run():
        gen = llm.stream_chat("m", [{"role": "user", "content": "x"}])
        async for _tok in gen:          # recebe o 1º token → worker já começou
            await gen.aclose()          # "parar"
            break

    asyncio.run(run())
    assert captured["cancel"] is not None
    assert captured["cancel"].is_set()  # o finally do stream_chat cancelou a geração


def test_stream_chat_propaga_erro_do_worker():
    class _Boom:
        name = "boom"
        def stream(self, *a, **k):
            yield "primeiro"
            raise RuntimeError("estourou no meio")
        def complete(self, *a, **k):
            return ""
    _inject(_Boom())

    async def run():
        got = []
        async for tok in llm.stream_chat("m", [{"role": "user", "content": "x"}]):
            got.append(tok)
        return got

    with pytest.raises(RuntimeError, match="estourou no meio"):
        asyncio.run(run())


# ── stream_sync ──────────────────────────────────────────────────
def test_stream_sync_produz_tokens_pelo_provedor():
    fp = _FakeProvider(tokens=["x", "y"])
    _inject(fp)
    assert list(llm.stream_sync("m", [{"role": "user", "content": "q"}])) == ["x", "y"]


# ── chat_resilient (retry + breaker) ─────────────────────────────
def test_chat_resilient_retorna_texto():
    _inject(_FakeProvider(complete_text="resposta"))
    assert llm.chat_resilient("m", [{"role": "user", "content": "q"}]) == "resposta"


def test_chat_resilient_retenta_falha_transitoria():
    fp = _FakeProvider(complete_text="recuperou", fail_times=1)
    _inject(fp)
    # attempts=2 → 1 falha + 1 sucesso. Deve devolver o texto, não levantar.
    assert llm.chat_resilient("m", [{"role": "user", "content": "q"}]) == "recuperou"
    assert fp.calls == 2


def test_chat_resilient_abre_breaker_e_rejeita_rapido():
    # Falha sempre → esgota retries e acumula falhas no breaker (fail_max=4).
    _inject(_FakeProvider(fail_times=999))
    for _ in range(4):
        with pytest.raises(ConnectionError):
            llm.chat_resilient("m", [{"role": "user", "content": "q"}])
    assert llm._ollama_breaker.state == "open"
    # Com o circuito aberto, rejeita sem nem chamar o provedor.
    fresh = _FakeProvider(complete_text="nunca chamado")
    _inject(fresh)
    with pytest.raises(CircuitOpenError):
        llm.chat_resilient("m", [{"role": "user", "content": "q"}])
    assert fresh.calls == 0
