"""Ritmo & tom (M17.2): o Apolo ajusta QUANTO fala conforme o estilo do Leo.

Determinístico e reversível: lê as preferências/valores do modelo profundo
(M16) e deriva um tom — direto, detalhado ou equilibrado — que vira uma
diretriz no system prompt. O Leo controla via as próprias preferências
(curadas no painel "Sobre mim"), então é transparente e reversível.
"""

from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger("apolo.style")

# Categorias do perfil que sinalizam preferência de estilo.
_STYLE_CATEGORIES = ("preference", "value")

# Palavras-sinal (sem acento, minúsculas). Ordem não importa; conta o placar.
_DIRECT_CUES = (
    "direto", "direta", "conciso", "concisa", "objetivo", "objetiva", "curto",
    "curta", "sucinto", "sucinta", "sem rodeio", "sem enrolacao", "pratico",
    "pratica", "ao ponto", "resumido", "rapido", "breve",
)
_DETAILED_CUES = (
    "detalhado", "detalhada", "completo", "completa", "aprofundado", "profundo",
    "passo a passo", "explica", "explicativo", "didatico", "didatica",
    "exemplos", "contexto", "minucioso", "elaborado",
)

TONES = ("direct", "detailed", "balanced")

_DIRECTIVES = {
    "direct": ("Estilo de resposta: seja DIRETO e conciso. Vá direto ao ponto, "
               "sem preâmbulos longos nem repetição."),
    "detailed": ("Estilo de resposta: seja DETALHADO. Explique o raciocínio, "
                 "dê exemplos e o contexto necessário."),
    "balanced": "",  # equilibrado = comportamento padrão, sem diretriz
}

_TONE_LABELS = {"direct": "Direto", "detailed": "Detalhado", "balanced": "Equilibrado"}


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _score(text: str, cues: tuple[str, ...]) -> int:
    low = _norm(text)
    return sum(1 for c in cues if c in low)


def derive_tone(profile) -> str:
    """Lê as preferências do perfil e decide o tom. 'balanced' se não há sinal
    ou se há empate (não impõe estilo sem evidência clara)."""
    if not profile:
        return "balanced"
    try:
        groups = profile.by_category()
    except Exception as e:
        logger.debug(f"style derive: {e}")
        return "balanced"
    texts = [f.get("fact", "") for cat in _STYLE_CATEGORIES for f in groups.get(cat, [])]
    blob = " ".join(texts)
    direct, detailed = _score(blob, _DIRECT_CUES), _score(blob, _DETAILED_CUES)
    if direct > detailed:
        return "direct"
    if detailed > direct:
        return "detailed"
    return "balanced"


def style_directive(tone: str) -> str:
    """Diretriz de estilo p/ o system prompt (vazia p/ equilibrado)."""
    return _DIRECTIVES.get(tone, "")


def describe(profile) -> dict:
    """Estado do tom — transparente/mensurável p/ o /api/style e a UI."""
    tone = derive_tone(profile)
    return {"tone": tone, "label": _TONE_LABELS[tone],
            "directive": style_directive(tone),
            "adapted": tone != "balanced"}
