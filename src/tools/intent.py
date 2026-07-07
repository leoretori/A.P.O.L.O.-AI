"""Ponte linguagem-natural → ferramenta de agência (M6, Épico 6.3, DoD).

Determinística e testável: uma frase do usuário vira (tool, args); o resultado do
run_tool vira uma resposta legível. Fica FORA do chat principal — é chamada por um
endpoint dedicado (/api/agency/ask), então não interfere no fluxo de conversa nem
no aprendizado. A janela temporal ('hoje'/'amanhã'/'semana') é extraída pela
própria ferramenta (email._since / calendar.window_for), então basta repassar a
frase inteira.
"""
from __future__ import annotations

import re

_RE_CLOCK = re.compile(r"que horas|que dia (é|e)|hora (certa|agora|é)|"
                       r"qual (é )?(a )?hora|data de hoje", re.I)
_RE_EMAIL = re.compile(r"\be-?mails?\b|caixa de entrada|inbox", re.I)
_RE_AGENDA = re.compile(r"\bagenda\b|\bcalend[aá]rio\b|compromisso|"
                        r"reuni[aã]o|\beventos?\b|o que (eu )?tenho", re.I)
_RE_READ = re.compile(r"(?:l[êe]r?|leia|abr[ae]|mostr[ae]|resum[ae]).*?"
                      r"\barquivo\b\s+(?P<path>.+)$", re.I)
_RE_SEARCH = re.compile(r"\b(?:busca[r]?|procur[ae]|encontr[ae]|list[ae])\b.*?"
                        r"\barquivos?\b(?P<q>.*)$", re.I)


def detect_intent(text: str) -> tuple[str, dict] | None:
    """Frase → (nome_da_ferramenta, args). None se nada casar."""
    t = (text or "").strip()
    if not t:
        return None
    if _RE_CLOCK.search(t):
        return "clock", {}
    m = _RE_READ.search(t)
    if m:
        return "files.read", {"path": m.group("path").strip().strip('"').strip("'")}
    if _RE_SEARCH.search(t):
        q = _RE_SEARCH.search(t).group("q")
        q = re.sub(r"^\s*(?:chamad[oa]s?|com|de|sobre|que|:)?\s*", "", q).strip()
        return "files.search", {"query": q}
    if _RE_EMAIL.search(t):
        return "email.recent", {"since": t}          # a ferramenta extrai a janela
    if _RE_AGENDA.search(t):
        return "calendar.events", {"when": t}
    return None


def _fmt_email(res: dict) -> str:
    n = res.get("count", 0)
    if not n:
        return "Nenhum e-mail no período."
    linhas = [f"Você tem {n} e-mail(s):"]
    for e in res.get("emails", []):
        linhas.append(f"• {e.get('from','?')} — {e.get('subject','(sem assunto)')}")
    return "\n".join(linhas)


def _fmt_calendar(res: dict) -> str:
    n = res.get("count", 0)
    quando = res.get("when", "")
    if not n:
        return f"Nada na agenda ({quando})." if quando else "Nada na agenda."
    linhas = [f"Você tem {n} compromisso(s):"]
    for ev in res.get("events", []):
        hora = "" if ev.get("all_day") else " " + ev.get("start", "")[11:16]
        local = f" ({ev['location']})" if ev.get("location") else ""
        linhas.append(f"• {ev.get('summary','(sem título)')}{hora}{local}")
    return "\n".join(linhas)


def _fmt_files_search(res: dict) -> str:
    n = res.get("count", 0)
    if not n:
        return "Nenhum arquivo encontrado."
    linhas = [f"{n} arquivo(s):"]
    for f in res.get("results", []):
        linhas.append(f"• {f.get('name','?')} — {f.get('path','')}")
    return "\n".join(linhas)


def _fmt_files_read(res: dict) -> str:
    content = res.get("content", "")
    head = content[:1500]
    trunc = "\n…(conteúdo truncado)" if (res.get("truncated") or len(content) > 1500) else ""
    return f"{res.get('path','')}:\n\n{head}{trunc}"


def _fmt_clock(res: dict) -> str:
    return (f"Agora são {res.get('time', '?')}, {res.get('weekday', '')}-feira "
            f"({res.get('date', '')}).").replace("sábado-feira", "sábado") \
        .replace("domingo-feira", "domingo")


_FORMATTERS = {
    "clock": _fmt_clock,
    "email.recent": _fmt_email,
    "calendar.events": _fmt_calendar,
    "files.search": _fmt_files_search,
    "files.read": _fmt_files_read,
}


def format_answer(tool_name: str, result: dict) -> str:
    fmt = _FORMATTERS.get(tool_name)
    return fmt(result or {}) if fmt else str(result)
