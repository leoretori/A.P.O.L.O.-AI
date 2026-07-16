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


def sector_prompt(text: str) -> str:
    """Formata o texto e pede a continuação 'Setor:' (tarefa de classificação)."""
    return f"{(text or '').strip()[:240]}\n\nSetor: "


def nano_classify_sector(engine, text: str, labels: list[str],
                         seed: int | None = None) -> str | None:
    """Classifica `text` num dos `labels` via Nano; None se não casar nenhum.

    Conjunto FECHADO: a saída do modelo é comparada com os rótulos conhecidos
    (casa por prefixo, tolerando tokens extras). NUNCA levanta exceção.
    """
    try:
        if engine is None or not engine.available() or not labels:
            return None
        result = engine.complete(sector_prompt(text), max_tokens=8,
                                 temperature=0.3, top_k=10, seed=seed)
        out = result["text"].strip().lower()
        # 1ª "palavra" gerada (slug pode ter _); casa com o rótulo mais longo
        # que for prefixo do que o modelo emitiu.
        candidates = sorted(labels, key=len, reverse=True)
        for label in candidates:
            if out.startswith(label.lower()):
                return label
        # fallback: rótulo cujo 1º termo aparece no começo da saída
        first = re.split(r"[\s\n]", out)[0] if out else ""
        for label in candidates:
            if first and label.lower().startswith(first) and len(first) >= 4:
                return label
        return None
    except Exception as e:
        logger.debug(f"Nano setor falhou: {e}")
        return None


_YES = ("sim", "s")
_NO = ("não", "nao", "n")


def binary_prompt(text: str, question: str) -> str:
    """Formata o texto + a pergunta binária e pede a continuação (mesmo
    template do treino em `taskdata.BINARY_TEMPLATE`)."""
    return f"{(text or '').strip()[:240]}\n\n{question} "


def nano_binary_classify(engine, text: str, question: str,
                         seed: int | None = None) -> bool | None:
    """Responde sim/não via Nano; None se indisponível ou a saída não casar
    nenhum dos dois (o portão de qualidade — melhor recusar que inventar).

    Tarefa FECHADA de propósito (2 classes só) — a aposta do M27+ é que um
    modelo pequeno generaliza binário melhor que multi-classe (M4.3 mediu
    31,4% em 9 classes); ainda não promovida a produção até medir de verdade
    com dado suficiente (ver `taskdata.collect_binary_pairs`). NUNCA levanta
    exceção — o fallback do chamador decide o que fazer.
    """
    try:
        if engine is None or not engine.available():
            return None
        result = engine.complete(binary_prompt(text, question), max_tokens=4,
                                 temperature=0.2, top_k=5, seed=seed)
        out = result["text"].strip().lower()
        first = re.split(r"[\s\n.,!?]", out)[0] if out else ""
        if first in _YES:
            return True
        if first in _NO:
            return False
        return None
    except Exception as e:
        logger.debug(f"Nano binário falhou: {e}")
        return None


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
