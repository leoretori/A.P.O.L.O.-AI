"""Roteamento de modelo por complexidade da pergunta — lógica pura e testável.

Decide se uma pergunta vale o raciocínio do modelo pesado (14b) ou se o leve (rápido)
basta. Numa máquina CPU-only o 14b é lento, então a regra equilibra: escala para o
14b quando a pergunta é genuinamente complexa, sem fazer isso em conversa trivial.
"""

# Pistas FORTES: uma só já justifica o 14b (são temas onde o raciocínio mais profundo
# faz diferença real na qualidade da resposta).
STRONG_CUES = (
    "arquitetura", "architecture", "otimiz", "optimiz", "trade-off", "tradeoff",
    "escalá", "scalab", "refator", "refactor", "design pattern", "padrão de projeto",
    "estratégia", "strategy", "prós e contras", "pros and cons", "passo a passo",
    "step by step", "demonstr", "prove ", "compare", "comparar", "compará",
)

# Pistas SUAVES: sozinhas são fracas; somam para decidir em perguntas mais longas.
SOFT_CUES = (
    "por que", "porque", " why ", "explique", "explica", "como funciona",
    "diferença", "difference", "vantagens", "desvantagens", "melhor", "best ",
    "in depth", "em detalhe", "analise", "analyze", "analisar", "avalie",
)


def is_complex(question: str) -> bool:
    """True se a pergunta merece o modelo pesado (14b)."""
    if not question:
        return False
    q = question.lower()
    # Sinais decisivos: código colado, pergunta muito longa, ou várias perguntas.
    if "```" in question or len(question) > 350:
        return True
    if q.count("?") >= 3:
        return True
    words = len(question.split())
    # Uma pista FORTE basta, desde que não seja uma frase trivial.
    if any(c in q for c in STRONG_CUES) and words >= 8:
        return True
    # Senão, exige acúmulo de pistas suaves em uma pergunta com alguma substância.
    soft = sum(1 for c in SOFT_CUES if c in q)
    return soft >= 2 and words >= 12


# Comando de agência só é roteado como 'tool' se for CURTO e direto — evita
# sequestrar uma pergunta longa que por acaso casa um regex de intenção.
_MAX_TOOL_WORDS = 10


def route_task(text: str) -> dict:
    """Classifica a mensagem numa ROTA de execução, poupando CPU:
      - 'tool'  : comando de agência curto (relógio/agenda/e-mail/arquivos) → run_tool, SEM LLM
      - 'heavy' : pergunta complexa → modelo 14b
      - 'light' : conversa/pergunta simples → modelo leve
    Também marca `factual` (candidata à verificação anti-alucinação do 7.2).
    Imports preguiçosos: mantém este módulo de baixo nível sem efeitos de import."""
    t = (text or "").strip()
    if not t:
        return {"route": "light", "model": "light", "tool": None,
                "factual": False, "reason": "vazio"}

    from src.graph import parse_connect_question
    from src.tools.intent import detect_intent
    from src.verify import is_factual_question

    # "como X se conecta com Y?" → grafo de conhecimento (M8 8.3), sem LLM.
    conn = parse_connect_question(t)
    if conn:
        return {"route": "connect", "model": None, "tool": None,
                "a": conn[0], "b": conn[1], "factual": False,
                "reason": "pergunta de conexão entre tópicos"}

    intent = detect_intent(t)
    words = len(t.split())
    # Rota de ferramenta só para comando curto e não-complexo (conservador).
    if intent and words <= _MAX_TOOL_WORDS and not is_complex(t):
        return {"route": "tool", "model": None, "tool": intent[0],
                "args": intent[1], "factual": False,
                "reason": f"comando de ferramenta ({intent[0]})"}

    heavy = is_complex(t)
    return {"route": "heavy" if heavy else "light",
            "model": "heavy" if heavy else "light", "tool": None,
            "factual": is_factual_question(t),
            "reason": "pergunta complexa" if heavy else "pergunta simples/conversa"}
