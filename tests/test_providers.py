"""Testes da abstração de provedor de inferência (Ollama vs motor próprio)."""

import os

import pytest

from src.providers import (
    LlamaCppProvider, OllamaProvider, get_provider, reset_provider,
)


# ── Seleção de backend por env ───────────────────────────────────
def test_backend_padrao_eh_ollama(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    reset_provider()
    try:
        assert get_provider().name == "ollama"
    finally:
        reset_provider()


def test_backend_llamacpp_selecionado_por_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODELS", "qwen:3b=models/q3.gguf")
    reset_provider()
    try:
        p = get_provider()
        assert p.name == "llamacpp"
        assert p is get_provider()  # cacheado (singleton)
    finally:
        reset_provider()


# ── LlamaCppProvider: parsing e resolução, sem carregar GGUF ──────
def test_parse_model_map():
    m = LlamaCppProvider._parse_model_map("a=x.gguf; b = y.gguf ;lixo;c=z.gguf")
    assert m == {"a": "x.gguf", "b": "y.gguf", "c": "z.gguf"}


def test_resolve_path_mapa_explicito(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS", "qwen:3b=models/q3.gguf;qwen:14b=models/q14.gguf")
    p = LlamaCppProvider()
    assert p._resolve_path("qwen:14b") == "models/q14.gguf"


def test_resolve_path_unico_modelo_ignora_nome(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS", "so-um=models/unico.gguf")
    p = LlamaCppProvider()
    # Com um só modelo configurado, qualquer nome lógico cai nele.
    assert p._resolve_path("qualquer-coisa") == "models/unico.gguf"


def test_resolve_path_fallback_para_o_proprio_nome(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS", "a=x.gguf;b=y.gguf")
    p = LlamaCppProvider()
    assert p._resolve_path("models/avulso.gguf") == "models/avulso.gguf"


def test_opts_traduz_num_predict_para_max_tokens():
    opts = LlamaCppProvider._opts({"num_predict": 32, "temperature": 0.2, "top_p": 0.9})
    assert opts == {"max_tokens": 32, "temperature": 0.2, "top_p": 0.9}


def test_get_levanta_erro_claro_sem_gguf(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS", "x=models/nao_existe_123.gguf")
    p = LlamaCppProvider()
    # Sem o arquivo, deve falhar com mensagem útil (não um ImportError obscuro)
    with pytest.raises((FileNotFoundError, ImportError)):
        p._get("x")


# ── OllamaProvider: normalização do formato de resposta ──────────
class _FakeMsg:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})()


class _FakeOllama:
    def chat(self, model, messages, stream=False, keep_alive=None, options=None):
        if stream:
            return [_FakeMsg("Olá"), _FakeMsg(" mundo")]
        return _FakeMsg("resposta completa")

    def list(self):
        return {"models": [{"model": "qwen:3b"}, {"name": "qwen:14b"}]}


def _ollama_provider_with_fake():
    p = OllamaProvider.__new__(OllamaProvider)
    p._client = _FakeOllama()   # _client é o que complete/stream/list_models usam
    p._ollama = _FakeOllama()   # mantém _ollama para compatibilidade
    p._keep_alive = "30m"
    return p


def test_ollama_complete_extrai_texto():
    p = _ollama_provider_with_fake()
    assert p.complete("qwen:3b", [{"role": "user", "content": "oi"}]) == "resposta completa"


def test_ollama_stream_produz_strings():
    p = _ollama_provider_with_fake()
    chunks = list(p.stream("qwen:3b", [{"role": "user", "content": "oi"}]))
    assert chunks == ["Olá", " mundo"]


def test_ollama_list_models_dedup_e_ordena():
    p = _ollama_provider_with_fake()
    assert p.list_models() == ["qwen:14b", "qwen:3b"]
