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


def test_resolve_path_nome_desconhecido_cai_no_primeiro(monkeypatch):
    # Vários modelos + nome fora do mapa (ex.: 'qwen2.5-coder:14b' legado do Ollama)
    # → cai no PRIMEIRO configurado em vez de quebrar. Era o bug que pausava o estudo.
    monkeypatch.setenv("LLAMACPP_MODELS", "a=x.gguf;b=y.gguf")
    p = LlamaCppProvider()
    assert p._resolve_path("qwen2.5-coder:14b") == "x.gguf"


def test_resolve_path_sem_mapa_devolve_o_nome(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS", "")
    p = LlamaCppProvider()
    assert p._resolve_path("models/avulso.gguf") == "models/avulso.gguf"


def test_llamacpp_serializa_geracoes_no_mesmo_modelo(monkeypatch):
    # Duas gerações simultâneas no MESMO modelo llama.cpp corrompem o buffer e
    # estouram GGML_ASSERT (repack.cpp) → crash. O lock por instância serializa.
    import threading
    import time
    monkeypatch.setenv("LLAMACPP_MODELS", "m=x.gguf")
    p = LlamaCppProvider()
    overlaps, active, guard = [], {"n": 0}, threading.Lock()

    class _FakeLlama:
        def create_chat_completion(self, messages, stream=False, **kw):
            with guard:
                active["n"] += 1
                if active["n"] > 1:
                    overlaps.append(True)          # duas gerações ao mesmo tempo!
            time.sleep(0.03)
            with guard:
                active["n"] -= 1
            return {"choices": [{"message": {"content": "ok"}}]}

    p._loaded["x.gguf"] = _FakeLlama()             # injeta já "carregado"
    p._locks["x.gguf"] = threading.Lock()
    ts = [threading.Thread(target=lambda: p.complete("m", [{"role": "user", "content": "oi"}]))
          for _ in range(5)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert overlaps == []                          # nenhuma sobreposição = serializado


def test_llamacpp_stream_aborta_com_cancel_e_libera_lock(monkeypatch):
    # "Parar" no front aborta o fetch → o consumidor sinaliza `cancel`. A geração
    # tem que ENCERRAR (não seguir até o teto) e LIBERAR o lock, senão o estudo (mesmo
    # 1.5B) fica travado esperando o lock. Era o bug do "gerou até 132 mesmo parando".
    import threading
    monkeypatch.setenv("LLAMACPP_MODELS", "m=x.gguf")
    p = LlamaCppProvider()
    cancel = threading.Event()

    class _FakeLlama:
        def create_chat_completion(self, messages, stream=False, **kw):
            assert stream is True
            def gen():
                for i in range(1000):                # "runaway" — mil tokens
                    yield {"choices": [{"delta": {"content": f"t{i} "}}]}
            return gen()

    p._loaded["x.gguf"] = _FakeLlama()
    p._locks["x.gguf"] = threading.Lock()

    out = []
    for i, piece in enumerate(p.stream("m", [{"role": "user", "content": "oi"}], cancel=cancel)):
        out.append(piece)
        if i == 4:
            cancel.set()                              # usuário clicou "parar"
    assert len(out) <= 6                              # parou logo após o cancel
    # O `with lock` saiu ao quebrar o laço → o lock está livre (estudo pode seguir).
    assert p._locks["x.gguf"].acquire(blocking=False)
    p._locks["x.gguf"].release()


def test_ollama_stream_aborta_com_cancel():
    p = _ollama_provider_with_fake()
    import threading
    cancel = threading.Event()
    cancel.set()                                      # já cancelado antes do 1º chunk
    assert list(p.stream("qwen:3b", [{"role": "user", "content": "oi"}], cancel=cancel)) == []


def test_opts_traduz_num_predict_para_max_tokens(monkeypatch):
    monkeypatch.delenv("LLAMACPP_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY", raising=False)
    p = LlamaCppProvider()
    opts = p._opts({"num_predict": 32, "temperature": 0.2, "top_p": 0.9})
    # num_predict do chamador vence; repeat_penalty entra por padrão (E19: o
    # piso agora é 1.1, do llama.cpp — 1.3 fica para os modelos pequenos).
    assert opts == {"max_tokens": 32, "temperature": 0.2, "top_p": 0.9, "repeat_penalty": 1.1}


def test_opts_teto_padrao_sempre_presente(monkeypatch):
    """Sem num_predict, o motor NUNCA gera ilimitado — cai no teto padrão. Foi a
    ausência disso que deixou o 1.5B entrar em loop e travar o lock (chat+estudo)."""
    monkeypatch.delenv("LLAMACPP_MAX_TOKENS", raising=False)
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY", raising=False)
    p = LlamaCppProvider()
    opts = p._opts(None)
    assert opts["max_tokens"] == 2048          # teto de segurança
    assert opts["repeat_penalty"] == 1.1       # piso; o pequeno sobe p/ 1.3
    opts2 = p._opts({})
    assert opts2["max_tokens"] == 2048


def test_opts_teto_configuravel_por_env(monkeypatch):
    monkeypatch.setenv("LLAMACPP_MAX_TOKENS", "512")
    monkeypatch.setenv("LLAMACPP_REPEAT_PENALTY", "1.2")
    p = LlamaCppProvider()
    opts = p._opts(None)
    assert opts["max_tokens"] == 512
    assert opts["repeat_penalty"] == 1.2


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


# ── E19: penalidade de repetição POR MODELO ─────────────────────────────
def test_penalidade_maior_so_para_o_modelo_pequeno(monkeypatch):
    """1.3 existia por causa do 1.5B degenerar — mas castigava o 7B, que
    precisa reusar tokens em código/JSON (`{`, `def`, vírgulas)."""
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY", raising=False)
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY_MAP", raising=False)
    p = LlamaCppProvider()
    assert p._opts(None, "qwen-1.5b")["repeat_penalty"] == 1.3
    assert p._opts(None, "qwen-7b")["repeat_penalty"] == 1.1
    assert p._opts(None, "")["repeat_penalty"] == 1.1


def test_penalidade_por_heuristica_de_nome(monkeypatch):
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY", raising=False)
    monkeypatch.setenv("LLAMACPP_REPEAT_PENALTY_MAP", "")
    p = LlamaCppProvider()
    assert p._penalty_for("algum-modelo-0.5b-instruct") == 1.3
    assert p._penalty_for("llama-3-8b") == 1.1


def test_mapa_de_penalidade_por_env(monkeypatch):
    monkeypatch.setenv("LLAMACPP_REPEAT_PENALTY_MAP", "meu-modelo=1.05;outro=1.4")
    p = LlamaCppProvider()
    assert p._penalty_for("meu-modelo") == 1.05
    assert p._penalty_for("outro") == 1.4


def test_chamador_ainda_manda_na_penalidade(monkeypatch):
    monkeypatch.delenv("LLAMACPP_REPEAT_PENALTY", raising=False)
    p = LlamaCppProvider()
    assert p._opts({"repeat_penalty": 1.02}, "qwen-1.5b")["repeat_penalty"] == 1.02
