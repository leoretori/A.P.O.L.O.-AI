"""Tarefas de produto servidas pelo Apolo-Nano (Épico 3.3).

O v1 é um modelo BASE (completa texto, não segue instrução), então cada
tarefa é formulada como continuação de um padrão que ele viu no corpus, e um
PORTÃO DE QUALIDADE determinístico decide se a saída presta — senão o chamador
cai no LLM grande. O Nano tenta primeiro; o fallback é garantido.

Tarefa 1: título de conversa. O corpus soberano está cheio de "Tópico: X",
então o prompt termina em "Tópico:" e o modelo completa com um candidato.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 60
TITLE_MAX_WORDS = 8

_MD_NOISE = re.compile(r"(#{2,}|\*\*|\||https?://|<[^>]+>|```)")
_LETTER = re.compile(r"[a-zA-Zà-üÀ-Ü]")


def title_prompt(message: str) -> str:
    """Formata a 1ª mensagem como contexto e pede a continuação 'Tópico:'."""
    return f"{(message or '').strip()[:200]}\n\nTópico: "


def extract_title(completion: str) -> str:
    """1ª linha da completion → candidato limpo (sem markdown, sem rabicho)."""
    line = (completion or "").strip().split("\n")[0]
    line = line.strip(" \"'`*#-—:.,;!?")
    line = re.sub(r"\s+", " ", line)
    # corta em pontuação de fim de frase (título não tem ponto final)
    line = re.split(r"[.!?:;]\s", line)[0].strip(" \"'`*#-—:.,;!?")
    if len(line) > TITLE_MAX_CHARS:  # corta em fronteira de palavra
        line = line[:TITLE_MAX_CHARS].rsplit(" ", 1)[0]
    return line.strip()


def title_ok(title: str) -> bool:
    """Portão de qualidade determinístico — melhor recusar do que salvar lixo."""
    if not title or not (3 <= len(title) <= TITLE_MAX_CHARS):
        return False
    if _MD_NOISE.search(title):
        return False
    words = title.split()
    if len(words) > TITLE_MAX_WORDS:
        return False
    # loop degenerativo: mesma palavra (>2 chars) 3+ vezes
    freqs: dict[str, int] = {}
    for w in words:
        lw = w.lower()
        if len(lw) > 2:
            freqs[lw] = freqs.get(lw, 0) + 1
            if freqs[lw] >= 3:
                return False
    # tem que ser majoritariamente texto (letras/espaços), não símbolo/número
    letters = len(_LETTER.findall(title))
    return letters / len(title) >= 0.6


def _norm(word: str) -> str:
    """minúsculas sem acento, radical de 4 chars — casa singular/plural."""
    trans = str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")
    return word.lower().translate(trans)[:4]


def title_relevant(title: str, message: str) -> bool:
    """O título precisa compartilhar 1+ palavra de CONTEÚDO com a mensagem.

    Um modelo base pequeno gera títulos bem-formados porém sem relação
    ("AWS S3" p/ pergunta de asyncio — visto no v1 real). Forma não basta.
    """
    msg_words = {_norm(w) for w in re.findall(r"\w{4,}", message or "")}
    title_words = {_norm(w) for w in re.findall(r"\w{4,}", title or "")}
    return bool(msg_words & title_words)


def nano_session_title(engine, message: str, seed: int | None = None) -> str | None:
    """Título via Apolo-Nano, ou None (qualidade insuficiente/indisponível).

    NUNCA levanta exceção — o fallback do chamador decide o que fazer.
    """
    try:
        if engine is None or not engine.available():
            return None
        result = engine.complete(title_prompt(message), max_tokens=16,
                                 temperature=0.5, top_k=20, seed=seed)
        title = extract_title(result["text"])
        if title_ok(title) and title_relevant(title, message):
            logger.info("Título via Apolo-Nano (%d tokens, %dms): %r",
                        result["tokens"], result["ms"], title)
            return title
        logger.debug("Nano título reprovado no portão: %r", title)
        return None
    except Exception as e:  # modelo próprio nunca pode derrubar o chat
        logger.debug(f"Nano título falhou: {e}")
        return None
