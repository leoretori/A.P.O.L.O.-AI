"""Palavra de ativação ("Apolo"/"Jarvis") — M5, Épico 5.1.

A escuta contínua transcreve trechos curtos (Whisper LOCAL via /api/stt) e
pergunta a este módulo: "começou com a palavra mágica?". A detecção é
DETERMINÍSTICA e testável, sem depender de lib de wake word nem de nuvem:

- normaliza (minúsculas, sem acento/pontuação, espaços colapsados);
- tolera preâmbulo comum ("ei/ok/oi/olá/hey") antes da wake word;
- casa a wake word por distância de edição ≤1 (tolera erro de transcrição:
  "apollo", "ápolo" → "apolo"), exigindo token ≥4 chars p/ evitar falso positivo;
- devolve o COMANDO após a wake word, já pronto p/ despachar
  ("Apolo, que horas são?" → "que horas são").

Wake words configuráveis por WAKE_WORDS (csv). Ativação por WAKE_ENABLED.
"""
from __future__ import annotations

import os
import re
import unicodedata

DEFAULT_WAKE = ("apolo", "jarvis")
# Preâmbulos ignorados antes da wake word ("ei apolo", "ok jarvis").
_FILLERS = {"ei", "ok", "oi", "ola", "hey", "escuta", "e", "opa"}
_MIN_LEN = 4          # token candidato precisa ter ≥4 chars p/ o fuzzy valer


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    """minúsculas, sem acento, só letras/números/espaço, espaços colapsados."""
    s = _strip_accents((text or "").lower())
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def wake_words() -> list[str]:
    raw = os.getenv("WAKE_WORDS", "").strip()
    words = [normalize(w) for w in raw.split(",")] if raw else list(DEFAULT_WAKE)
    return [w for w in words if w]


def is_enabled() -> bool:
    return os.getenv("WAKE_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def _edit_distance_le1(a: str, b: str) -> bool:
    """True se a e b diferem por ≤1 edição (subst/insert/delete). Rápido: só
    precisamos do limiar 1, não da distância exata."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:                                   # 1 substituição no máximo
        return sum(x != y for x, y in zip(a, b)) == 1
    # comprimentos diferem de 1 → um é o outro com 1 char inserido
    short, long = (a, b) if la < lb else (b, a)
    i = j = 0
    skipped = False
    while i < len(short) and j < len(long):
        if short[i] == long[j]:
            i += 1
            j += 1
        elif skipped:
            return False
        else:
            skipped = True
            j += 1
    return True


def _matches_wake(token: str, phrases: list[str]) -> str | None:
    for w in phrases:
        if token == w:
            return w
        if len(token) >= _MIN_LEN and len(w) >= _MIN_LEN and _edit_distance_le1(token, w):
            return w
    return None


def detect(text: str, phrases: list[str] | None = None) -> dict:
    """Detecta a wake word no INÍCIO do trecho (após preâmbulo opcional).
    Retorna {woke, phrase, command}. command = o que veio depois da wake word."""
    phrases = phrases or wake_words()
    tokens = normalize(text).split()
    i = 0
    # pula preâmbulos ("ei", "ok"...)
    while i < len(tokens) and tokens[i] in _FILLERS:
        i += 1
    if i >= len(tokens):
        return {"woke": False, "phrase": "", "command": ""}
    matched = _matches_wake(tokens[i], phrases)
    if not matched:
        return {"woke": False, "phrase": "", "command": ""}
    command = " ".join(tokens[i + 1:]).strip()
    return {"woke": True, "phrase": matched, "command": command}
