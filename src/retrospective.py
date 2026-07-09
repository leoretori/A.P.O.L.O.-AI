"""Retrospectiva do ano (M12, Épico 12.2).

O A.P.O.L.O. olha para trás — o que aprendeu, construiu e mediu — e para frente:
propõe os focos do ANO 2. É o DoD do M12: um resumo FALÁVEL do que fez no ano e do
que sugere para o próximo.

`compose_retrospective_text` monta a narrativa PT-BR (determinística, sem LLM,
pronta para o TTS) a partir de números que já coletamos. `year_two_themes` combina
as metas concretas das métricas atuais (reusa o `propose_goals` do 12.1) com temas
estratégicos de longo prazo. Testável: mesmos dados → mesmo texto.
"""
from __future__ import annotations


def _plural(n: int, s: str, p: str) -> str:
    return f"{n} {s if n == 1 else p}"


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


# Temas estratégicos de longo prazo (aspiracionais, além das métricas do dia).
STRATEGIC_THEMES = [
    "um cérebro maior quando houver GPU (fine-tuning e modelos além de 14B)",
    "mais agência no mundo real (apps nativos e navegador interativo)",
    "uma memória ainda mais profunda de quem você é",
]


def year_two_themes(signals: dict, limit: int = 5) -> list[str]:
    """Focos propostos para o ano 2: metas concretas (das métricas de hoje) +
    temas estratégicos. Ordenado com o mais acionável primeiro."""
    from src.projects import propose_goals
    concrete = [g["title"] for g in propose_goals(signals or {})]
    themes = concrete + [t for t in STRATEGIC_THEMES]
    # remove duplicatas preservando ordem
    seen, out = set(), []
    for t in themes:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out[:limit]


def compose_retrospective_text(data: dict) -> str:
    """Narrativa falável do ano. `data` traz os números já medidos."""
    d = data or {}
    parts = ["Aqui está a retrospectiva do nosso ano."]

    topics = int(d.get("total_topics", 0) or 0)
    if topics:
        parts.append(f"Eu aprendi {_plural(topics, 'tópico', 'tópicos')} de forma autônoma"
                     + (f", em {_plural(int(d['active_days']), 'dia', 'dias')} ativos" if d.get("active_days") else "")
                     + ".")

    coder = d.get("coder") or {}
    if coder.get("total"):
        rate = coder.get("success_rate")
        parts.append(f"No Coder, encarei {_plural(int(coder['total']), 'tarefa', 'tarefas')}"
                     + (f", acertando {rate}% delas" if rate is not None else "") + ".")

    ev = d.get("eval") or {}
    if ev.get("score") is not None:
        frase = f"Na autoavaliação, minha nota está em {round(ev['score'] * 100)}%"
        if ev.get("hallucination_rate") is not None:
            frase += f", com {round(ev['hallucination_rate'] * 100)}% de alucinação nas armadilhas"
        parts.append(frase + ".")

    fb = d.get("feedback") or {}
    if (fb.get("up", 0) + fb.get("down", 0)) > 0:
        parts.append(f"Você me deu {_plural(int(fb.get('up', 0)), 'positivo', 'positivos')} "
                     f"e {_plural(int(fb.get('down', 0)), 'negativo', 'negativos')} — obrigado, isso me ajuda a melhorar.")

    if d.get("projects_done"):
        parts.append(f"Concluí {_plural(int(d['projects_done']), 'projeto de melhoria', 'projetos de melhoria')} que eu mesmo propus.")

    themes = d.get("year_two_themes") or []
    if themes:
        parts.append("Para o próximo ano, proponho focar em: " + _join(themes) + ".")
    parts.append("Seguimos juntos.")
    return " ".join(parts)


def build_retrospective(data: dict, signals: dict) -> dict:
    """Monta o pacote da retrospectiva: números + temas do ano 2 + texto falável."""
    themes = year_two_themes(signals)
    payload = {**(data or {}), "year_two_themes": themes}
    return {
        "highlights": {
            "total_topics": data.get("total_topics", 0),
            "active_days": data.get("active_days", 0),
            "coder": data.get("coder", {}),
            "eval": data.get("eval", {}),
            "feedback": data.get("feedback", {}),
            "projects_done": data.get("projects_done", 0),
        },
        "year_two_themes": themes,
        "text": compose_retrospective_text(payload),
    }
