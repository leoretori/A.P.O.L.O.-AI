"""Seleção de modelos — lógica pura e testável.

Extraída de `app.py` para isolar as heurísticas de escolha de modelo (chat leve e
visão) das chamadas de I/O. As funções abaixo não fazem rede: recebem a lista de
modelos já obtida do provedor ativo e decidem qual usar. Isso as torna unitariamente
testáveis e independentes do backend (Ollama ou motor próprio).
"""

# Marcadores de modelos de visão (heurística por nome).
VISION_MARKERS = ("llava", "vision", "moondream", "bakllava", "minicpm-v", "-vl", "qwen2.5vl")


def pick_chat_model(installed, light_preference, main_model: str, env_chat: str = "") -> str:
    """Escolhe um modelo leve para o chat (resposta rápida em CPU).

    Prioridade: `env_chat` explícito > 1º modelo da preferência leve que esteja
    instalado (e diferente do principal) > o modelo principal como fallback."""
    if env_chat:
        return env_chat
    installed = set(installed or [])
    for name in light_preference:
        if name in installed and name != main_model:
            return name
    return main_model


def pick_vision_model(installed, env_vision: str = "", markers=VISION_MARKERS) -> str:
    """Acha um modelo de visão instalado (env tem prioridade). '' se não houver."""
    if env_vision:
        return env_vision
    for name in (installed or []):
        if name and any(mk in name.lower() for mk in markers):
            return name
    return ""
