"""Retrospectiva do Ano 2 (M24, Épico 24.3) — o A.P.O.L.O. mostra, com
números, que ficou mais capaz, e propõe o Ano 3.

Mesmo padrão do M12.2 (`src/retrospective.py`, a retrospectiva do Ano 1):
narrativa PT-BR determinística, sem LLM, pronta pro TTS, montada a partir de
números que já medimos. Diferença honesta: aqui "propor o Ano 3" não é
hipótese — o roadmap (`JARVIS_ROADMAP_ANO2.md` §10) já tem progresso real
registrado (M25–M28); esta retrospectiva reporta ONDE esse trabalho está e
o que falta, em vez de inventar um plano do zero.
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


# Temas do Ano 3 — ancorados no que o roadmap já registrou como próximo passo
# (§10 do JARVIS_ROADMAP_ANO2.md), não inventados aqui.
YEAR_THREE_THEMES = [
    "crescer a cobertura do cérebro próprio — mais tarefas saindo do Qwen e indo pro Nano",
    "religar o dataset dos seus 👍 dentro do flywheel noturno automático",
    "compilar o motor com Vulkan pra usar a placa de vídeo integrada na inferência",
    "decidir a GPU dedicada com os números medidos até aqui, não por achismo",
]


def year3_themes(limit: int = 5) -> list[str]:
    """Focos propostos para o Ano 3 — direto do que o roadmap já apontou como
    próximo passo real (não aspiracional solto)."""
    return YEAR_THREE_THEMES[:limit]


def compose_retrospective2_text(data: dict) -> str:
    """Narrativa falável do Ano 2. `data` traz os números já medidos."""
    d = data or {}
    parts = ["Aqui está a retrospectiva do nosso segundo ano."]

    topics = int(d.get("total_topics", 0) or 0)
    if topics:
        parts.append(f"Eu aprendi {_plural(topics, 'tópico', 'tópicos')} de forma autônoma"
                     + (f", em {_plural(int(d['active_days']), 'dia', 'dias')} ativos" if d.get("active_days") else "")
                     + ".")

    nano = d.get("nano") or {}
    if nano.get("total"):
        parts.append(f"O cérebro próprio, o Apolo-Nano, já serve {nano['pct']}% das tarefas "
                     f"leves do dia — o resto ainda é o professor.")

    blind = d.get("blind_eval") or {}
    if blind.get("n"):
        parts.append(f"Numa avaliação às cegas contra o professor, o Nano venceu "
                     f"{blind['win_rate']}% de {_plural(int(blind['n']), 'pergunta', 'perguntas')}.")

    if d.get("projects_measured"):
        pm = d["projects_measured"]
        parts.append(f"Concluí {_plural(int(pm['total']), 'projeto de melhoria', 'projetos de melhoria')} "
                     f"e me re-medi sozinho em cada um — {_plural(int(pm['improved']), 'melhorou', 'melhoraram')} de verdade.")

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

    if d.get("vision_shipped"):
        parts.append("Também passei a ver: tela, documentos e câmera, sempre com sua permissão.")

    themes = d.get("year3_themes") or []
    if themes:
        parts.append("Para o Ano 3, o plano já em andamento é: " + _join(themes) + ".")
    parts.append("Seguimos juntos.")
    return " ".join(parts)


def build_retrospective2(data: dict) -> dict:
    """Monta o pacote da retrospectiva do Ano 2: números + temas do Ano 3 + texto falável."""
    themes = year3_themes()
    payload = {**(data or {}), "year3_themes": themes}
    return {
        "highlights": {
            "total_topics": data.get("total_topics", 0),
            "active_days": data.get("active_days", 0),
            "nano": data.get("nano", {}),
            "blind_eval": data.get("blind_eval", {}),
            "projects_measured": data.get("projects_measured", {}),
            "eval": data.get("eval", {}),
            "feedback": data.get("feedback", {}),
            "vision_shipped": data.get("vision_shipped", False),
        },
        "year3_themes": themes,
        "text": compose_retrospective2_text(payload),
    }
