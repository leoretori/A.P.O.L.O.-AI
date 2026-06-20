"""Testes do perfil de hardware / performance da inferência."""

import src.hardware as hw


def test_profile_padrao_balanced(monkeypatch):
    monkeypatch.delenv("APOLO_PERFORMANCE", raising=False)
    assert hw.profile() == "balanced"
    assert hw.is_max() is False


def test_profile_max(monkeypatch):
    monkeypatch.setenv("APOLO_PERFORMANCE", "MAX")
    assert hw.profile() == "max"
    assert hw.is_max() is True


def test_num_threads_auto_por_padrao(monkeypatch):
    monkeypatch.delenv("APOLO_NUM_THREAD", raising=False)
    assert hw.num_threads() is None   # None = deixa o motor decidir


def test_num_threads_configuravel(monkeypatch):
    monkeypatch.setenv("APOLO_NUM_THREAD", "6")
    assert hw.num_threads() == 6


def test_num_threads_invalido_volta_pra_auto(monkeypatch):
    monkeypatch.setenv("APOLO_NUM_THREAD", "abc")
    assert hw.num_threads() is None


def test_inference_options_balanced_minimo(monkeypatch):
    monkeypatch.delenv("APOLO_PERFORMANCE", raising=False)
    monkeypatch.delenv("APOLO_NUM_THREAD", raising=False)
    assert hw.inference_options() == {}   # sem nada forçado


def test_inference_options_max_usa_contexto(monkeypatch):
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    monkeypatch.delenv("APOLO_NUM_CTX", raising=False)
    opts = hw.inference_options()
    assert opts["num_ctx"] == 8192


def test_inference_options_inclui_threads_quando_setado(monkeypatch):
    monkeypatch.setenv("APOLO_NUM_THREAD", "6")
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    monkeypatch.setenv("APOLO_NUM_CTX", "4096")
    assert hw.inference_options() == {"num_thread": 6, "num_ctx": 4096}


def test_keep_alive_heavy_balanced_descarrega(monkeypatch):
    monkeypatch.delenv("APOLO_PERFORMANCE", raising=False)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE_HEAVY", raising=False)
    assert hw.keep_alive_heavy() == "0"


def test_keep_alive_heavy_max_mantem_quente(monkeypatch):
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE_HEAVY", raising=False)
    assert hw.keep_alive_heavy() == "30m"


def test_keep_alive_heavy_env_override(monkeypatch):
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE_HEAVY", "-1")
    assert hw.keep_alive_heavy() == "-1"


def test_summary_tem_campos(monkeypatch):
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    s = hw.summary()
    for k in ("profile", "num_thread", "num_ctx", "keep_alive_heavy", "cpu_count"):
        assert k in s


def test_provider_mescla_options_com_chamador_vencendo(monkeypatch):
    # O provedor Ollama deve mesclar inference_options(), mas o chamador tem prioridade.
    monkeypatch.setenv("APOLO_PERFORMANCE", "max")
    monkeypatch.setenv("APOLO_NUM_CTX", "8192")
    from src.providers import OllamaProvider
    p = OllamaProvider.__new__(OllamaProvider)
    merged = p._opts({"num_ctx": 2048, "temperature": 0.1})
    assert merged["num_ctx"] == 2048        # chamador venceu
    assert merged["temperature"] == 0.1
