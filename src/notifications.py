"""Política de relevância das notificações (M4, Épico 4.3).

O A.P.O.L.O. faz MUITA coisa sozinho (estuda o tempo todo), e transformar cada
evento num aviso vira RUÍDO. Aqui centralizamos:

- prioridade por tipo (0 = ruído de fundo … 3 = importante/acionável);
- quais tipos COLAPSAM (viram um único aviso rolante com contagem, em vez de N);
- a janela de colapso.

Assim o que importa (lembretes, briefing) aparece; o corriqueiro (cada tópico
estudado) é agrupado num só "📚 Estudei N tópicos".
"""

# 0 = ruído de fundo, 1 = informativo, 2 = relevante, 3 = importante/acionável.
KIND_PRIORITY = {
    "reminder": 3,
    "briefing": 3,
    "gap": 2,
    "synthesis": 2,
    "info": 1,
    "study": 0,
}
DEFAULT_PRIORITY = 1

# Tipos de baixa prioridade que colapsam num aviso único (evita spam).
COLLAPSIBLE_KINDS = {"study"}
COLLAPSE_WINDOW_MIN = 30   # colapsa no aviso não-lido do mesmo tipo dos últimos N min


def priority_for(kind: str) -> int:
    return KIND_PRIORITY.get(kind, DEFAULT_PRIORITY)


def collapses(kind: str) -> bool:
    return kind in COLLAPSIBLE_KINDS


def collapsed_message(kind: str, count: int, latest: str) -> str:
    """Mensagem do aviso colapsado — mostra a contagem e o último evento."""
    latest = (latest or "").strip()
    # Tira emoji/prefixo comum ("📚 Estudei: X" → "X") para o resumo ficar limpo.
    for sep in (": ", "— ", "- "):
        if sep in latest:
            latest = latest.split(sep, 1)[1]
            break
    if kind == "study":
        base = f"📚 Estudei {count} tópicos"
        return f"{base} (último: {latest[:80]})" if latest else base
    return f"{count}× {latest[:120]}"
