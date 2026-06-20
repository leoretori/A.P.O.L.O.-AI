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
