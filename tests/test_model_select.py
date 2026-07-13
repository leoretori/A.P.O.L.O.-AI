"""Testes da seleção de modelos (lógica pura extraída de app.py)."""

from src.model_select import (
    _model_size,
    pick_chat_model,
    pick_llamacpp_roles,
    pick_vision_model,
)


LIGHT_PREF = ["qwen2.5-coder:3b", "llama3.2:3b", "phi3:mini"]
MAIN = "qwen2.5-coder:14b"


# ── pick_llamacpp_roles (velocidade do chat: leve p/ chat, pesado p/ Inteligente) ──
def test_model_size_extrai_bilhoes():
    assert _model_size("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf") == 1.5
    assert _model_size("qwen-7b") == 7.0
    assert _model_size("sem-tamanho") == 0.0


def test_roles_menor_vira_chat_maior_vira_pesado():
    m = {"qwen-7b": "models/Qwen2.5-7B.gguf", "qwen-1.5b": "models/Qwen2.5-1.5B.gguf"}
    chat, heavy = pick_llamacpp_roles(m)
    assert chat == "qwen-1.5b" and heavy == "qwen-7b"


def test_roles_um_modelo_so_nao_divide():
    m = {"apolo": "models/Qwen2.5-7B.gguf"}
    assert pick_llamacpp_roles(m) == ("apolo", "apolo")


def test_roles_override_por_env():
    m = {"a": "x-3b.gguf", "b": "y-7b.gguf", "c": "z-1.5b.gguf"}
    assert pick_llamacpp_roles(m, env_chat="b", env_heavy="a") == ("b", "a")
    # env inexistente cai no automático (menor/maior)
    assert pick_llamacpp_roles(m, env_chat="zzz") == ("c", "b")


def test_roles_vazio():
    assert pick_llamacpp_roles({}) == ("", "")


# ── pick_chat_model ──────────────────────────────────────────────
def test_chat_env_explicito_tem_prioridade():
    assert pick_chat_model(["x"], LIGHT_PREF, MAIN, env_chat="meu-modelo") == "meu-modelo"


def test_chat_escolhe_primeiro_leve_instalado():
    installed = ["qwen2.5-coder:14b", "llama3.2:3b"]
    # 3b da preferência não está; o llama3.2:3b está → escolhe ele.
    assert pick_chat_model(installed, LIGHT_PREF, MAIN) == "llama3.2:3b"


def test_chat_respeita_ordem_de_preferencia():
    installed = ["phi3:mini", "qwen2.5-coder:3b", "llama3.2:3b"]
    # qwen3b vem primeiro na preferência → vence mesmo com outros instalados.
    assert pick_chat_model(installed, LIGHT_PREF, MAIN) == "qwen2.5-coder:3b"


def test_chat_fallback_para_principal_sem_leve():
    assert pick_chat_model(["qwen2.5-coder:14b"], LIGHT_PREF, MAIN) == MAIN


def test_chat_nunca_escolhe_o_proprio_principal_como_leve():
    # Se o principal estiver na preferência e instalado, não conta como "leve".
    pref = [MAIN, "llama3.2:3b"]
    assert pick_chat_model([MAIN, "llama3.2:3b"], pref, MAIN) == "llama3.2:3b"


def test_chat_lista_vazia_cai_no_principal():
    assert pick_chat_model([], LIGHT_PREF, MAIN) == MAIN
    assert pick_chat_model(None, LIGHT_PREF, MAIN) == MAIN


# ── pick_vision_model ────────────────────────────────────────────
def test_vision_env_tem_prioridade():
    assert pick_vision_model(["llava:7b"], env_vision="meu-vlm") == "meu-vlm"


def test_vision_detecta_por_marcador():
    assert pick_vision_model(["qwen2.5-coder:14b", "llava:7b"]) == "llava:7b"
    assert pick_vision_model(["moondream:latest"]) == "moondream:latest"
    assert pick_vision_model(["qwen2.5vl:7b"]) == "qwen2.5vl:7b"


def test_vision_vazio_quando_nao_ha_modelo_de_visao():
    assert pick_vision_model(["qwen2.5-coder:14b", "llama3.2:3b"]) == ""
    assert pick_vision_model([]) == ""
    assert pick_vision_model(None) == ""


def test_vision_ignora_none_na_lista():
    assert pick_vision_model([None, "llava:7b"]) == "llava:7b"
