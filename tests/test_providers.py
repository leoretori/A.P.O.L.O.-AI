"""Testes da abstração de provedor de inferência (Ollama vs motor próprio)."""


import pytest

from src.providers import (
    LlamaCppProvider, OllamaProvider, backend_status, get_provider, reset_provider,
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


# ── backend_status: "posso cortar o cordão do Ollama?" ──────────
def test_status_ollama_padrao(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    s = backend_status()
    assert s["backend"] == "ollama" and s["sovereign"] is False and s["ready"] is True


def test_status_llamacpp_falta_modelo(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.delenv("LLAMACPP_MODELS", raising=False)
    s = backend_status()
    assert s["backend"] == "llamacpp" and s["sovereign"] is True
    assert s["ready"] is False and "LLAMACPP_MODELS" in s["detail"]


def test_status_llamacpp_gguf_inexistente(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODELS", "x=models/nao_existe_999.gguf")
    s = backend_status()
    assert s["ready"] is False and "gguf" in s["detail"].lower()


def test_status_llamacpp_pronto(monkeypatch, tmp_path):
    gguf = tmp_path / "modelo.gguf"
    gguf.write_bytes(b"fake")
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODELS", f"meu={gguf}")
    # lib pode não estar instalada no CI → simula presença do módulo
    import importlib.util
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    s = backend_status()
    assert s["ready"] is True and "pronto" in s["detail"]


# ── M26: aceleração por iGPU/Vulkan — honesto sobre o que o build suporta ──
def _fake_llama_cpp(monkeypatch, supports):
    import importlib.util
    import sys
    import types
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    fake = types.ModuleType("llama_cpp")
    fake.llama_supports_gpu_offload = lambda: supports
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)


def test_status_gpu_build_sem_vulkan_avisa(monkeypatch, tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODELS", f"m={gguf}")
    monkeypatch.setenv("LLAMACPP_GPU_LAYERS", "8")
    _fake_llama_cpp(monkeypatch, supports=False)
    g = backend_status()["gpu"]
    assert g["layers_configured"] == 8 and g["offload_supported"] is False
    assert "Vulkan" in g["note"]                 # aponta o caminho de correção


def test_status_gpu_offload_ativo(monkeypatch, tmp_path):
    gguf = tmp_path / "m.gguf"
    gguf.write_bytes(b"x")
    monkeypatch.setenv("LLM_BACKEND", "llamacpp")
    monkeypatch.setenv("LLAMACPP_MODELS", f"m={gguf}")
    monkeypatch.setenv("LLAMACPP_GPU_LAYERS", "16")
    _fake_llama_cpp(monkeypatch, supports=True)
    g = backend_status()["gpu"]
    assert g["offload_supported"] is True and "offload ativo" in g["note"]


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
