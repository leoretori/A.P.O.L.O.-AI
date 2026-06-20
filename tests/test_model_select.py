"""Testes da seleção de modelos (lógica pura extraída de app.py)."""

from src.model_select import pick_chat_model, pick_vision_model


LIGHT_PREF = ["qwen2.5-coder:3b", "llama3.2:3b", "phi3:mini"]
MAIN = "qwen2.5-coder:14b"


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
