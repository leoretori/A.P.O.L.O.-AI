"""Projetos autodirigidos (M12, Épico 12.1).

O A.P.O.L.O. olha as PRÓPRIAS métricas e propõe metas de melhoria — vira um
backlog acionável ("suas sínteses estão 60% estruturadas → melhore isso"), quebra
cada meta em passos concretos, e acompanha o progresso. É automelhoria SUPERVISIONADA:
ele PROPÕE e reporta; quem aprova e executa é o Leo (a lição do 3B que reescreveu um
módulo inteiro para encaixar uma alucinação vale aqui — nada roda o Coder sozinho).

`propose_goals(signals)` e `break_into_tasks(goal)` são DETERMINÍSTICOS e testáveis
(nenhum LLM): as metas caem de limiares sobre sinais que já coletamos (qualidade de
síntese, acerto do Coder, alucinação, lacunas, duplicatas, feedback).
"""
from __future__ import annotations


# Cada tipo de meta: título, porquê (template com o valor), e os passos.
_TASKS = {
    "summary_quality": [
        "Abrir Saúde → 🩹 Reparar sínteses cruas",
        "Re-sintetizar as sínteses cruas (texto corrido → seções)",
        "Confirmar que o % de sínteses estruturadas subiu",
    ],
    "hallucination": [
        "Analytics → ▶ Rodar avaliação (suíte canário)",
        "Revisar as armadilhas que o modelo mordeu",
        "Reforçar a verificação/roteamento das perguntas factuais",
    ],
    "coder": [
        "Revisar as lições recentes do Coder",
        "Rodar algumas tarefas de teste no Coder",
        "Medir se a taxa de acerto melhorou",
    ],
    "gaps": [
        "Listar as lacunas (perguntas sem memória)",
        "Estudar cada lacuna (fila de estudo)",
        "Confirmar que o recall dessas lacunas melhorou",
    ],
    "dedup": [
        "Mente → limpar duplicatas da base",
        "Confirmar que a contagem de duplicatas caiu",
    ],
    "feedback": [
        "Ver os 👎 com motivo (feedback negativo)",
        "Corrigir os padrões que o Leo apontou",
        "Acompanhar se a taxa de 👍 sobe",
    ],
    "quality_regression": [
        "Comparar os últimos runs do eval canário",
        "Investigar o que mudou entre eles",
        "Corrigir e reavaliar",
    ],
}

_DEFAULT_TASKS = ["Definir o escopo", "Executar", "Medir o resultado"]


def break_into_tasks(goal: dict) -> list[str]:
    """Passos concretos para uma meta, por tipo. Determinístico."""
    return list(_TASKS.get(goal.get("kind"), _DEFAULT_TASKS))


def _g(id_, kind, title, why, priority) -> dict:
    return {"id": id_, "kind": kind, "title": title, "why": why, "priority": priority}


def propose_goals(signals: dict) -> list[dict]:
    """Deriva metas de melhoria dos sinais de saúde do próprio sistema. Cada meta
    tem uma prioridade (0=baixa … 3=urgente); volta ordenada, mais urgente primeiro.
    Só propõe o que os LIMIARES justificam (nada de ruído)."""
    s = signals or {}
    goals: list[dict] = []

    pct = s.get("pct_structured")
    raw = int(s.get("raw_summaries", 0) or 0)
    if raw > 0 or (pct is not None and pct < 90):
        pr = 3 if (pct is not None and pct < 60) else 2
        goals.append(_g("summary_quality", "summary_quality",
                        "Melhorar a qualidade das sínteses",
                        f"{raw} sínteses cruas" + (f" · {pct}% estruturadas" if pct is not None else ""),
                        pr))

    hr = s.get("hallucination_rate")
    if hr is not None and hr > 0.1:
        goals.append(_g("hallucination", "hallucination",
                        "Reduzir a taxa de alucinação",
                        f"{round(hr * 100)}% das armadilhas do eval foram mordidas",
                        3 if hr > 0.3 else 2))

    cs = s.get("coder_success")
    if cs is not None and cs < 70:
        goals.append(_g("coder", "coder",
                        "Melhorar o acerto do Coder",
                        f"taxa de acerto em {cs}%",
                        2 if cs >= 50 else 3))

    gaps = int(s.get("gap_count", 0) or 0)
    if gaps > 5:
        goals.append(_g("gaps", "gaps",
                        "Fechar as lacunas de conhecimento",
                        f"{gaps} perguntas sem memória detectadas",
                        1))

    dups = int(s.get("duplicates", 0) or 0)
    if dups > 20:
        goals.append(_g("dedup", "dedup",
                        "Limpar duplicatas da base",
                        f"{dups} registros duplicados",
                        1))

    down = int(s.get("down_votes", 0) or 0)
    if down >= 3:
        goals.append(_g("feedback", "feedback",
                        "Revisar respostas mal avaliadas",
                        f"{down} respostas com 👎",
                        2))

    trend = s.get("eval_score_trend")
    if trend is not None and trend < -0.05:
        goals.append(_g("quality_regression", "quality_regression",
                        "Investigar queda de qualidade",
                        f"nota do eval caiu {abs(round(trend, 3))}",
                        3))

    goals.sort(key=lambda g: g["priority"], reverse=True)
    return goals


def project_progress(tasks: list[dict]) -> int:
    """% de tarefas concluídas (0–100). tasks = [{text, done}]."""
    if not tasks:
        return 0
    done = sum(1 for t in tasks if t.get("done"))
    return round(100 * done / len(tasks))
