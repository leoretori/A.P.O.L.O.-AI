"""Seleção de modelos — lógica pura e testável.

Extraída de `app.py` para isolar as heurísticas de escolha de modelo (chat leve e
visão) das chamadas de I/O. As funções abaixo não fazem rede: recebem a lista de
modelos já obtida do provedor ativo e decidem qual usar. Isso as torna unitariamente
testáveis e independentes do backend (Ollama ou motor próprio).
"""

import re as _re

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


# Tokens de tamanho para ordenar GGUFs do motor próprio (bilhões de parâmetros).
_SIZE_RE = _re.compile(r"(\d+(?:\.\d+)?)\s*b\b", _re.IGNORECASE)


def _model_size(name_or_path: str) -> float:
    """Extrai o tamanho em B do nome/caminho (ex.: 'Qwen2.5-1.5B' → 1.5). 0 se
    não achar — assim um modelo sem marca de tamanho não vira 'pesado' por acaso."""
    m = _SIZE_RE.search(name_or_path or "")
    return float(m.group(1)) if m else 0.0


def pick_llamacpp_roles(models: dict, env_chat: str = "", env_heavy: str = "") -> tuple:
    """Divide os GGUFs do motor próprio em papéis (chat_leve, pesado).

    O chat do dia a dia usa o MENOR (resposta rápida em CPU); 'Inteligente'/pesado
    usa o MAIOR. Overrides explícitos por env têm prioridade. Com 1 só modelo, os
    dois papéis são ele mesmo (sem divisão — comportamento atual). Retorna nomes
    (chaves do mapa) — vazio se não houver modelos."""
    names = list(models or {})
    if not names:
        return ("", "")
    ordered = sorted(names, key=lambda n: _model_size(models[n] or n) or _model_size(n))
    light = env_chat if env_chat in models else ordered[0]
    heavy = env_heavy if env_heavy in models else ordered[-1]
    return (light, heavy)


def pick_vision_model(installed, env_vision: str = "", markers=VISION_MARKERS) -> str:
    """Acha um modelo de visão instalado (env tem prioridade). '' se não houver."""
    if env_vision:
        return env_vision
    for name in (installed or []):
        if name and any(mk in name.lower() for mk in markers):
            return name
    return ""
