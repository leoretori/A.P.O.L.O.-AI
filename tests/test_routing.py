"""Testes do roteamento de modelo por complexidade (src/routing.py)."""

from src.routing import is_complex


# ── Triviais → modelo leve (não escala) ──────────────────────────
def test_saudacao_nao_e_complexa():
    assert is_complex("oi, tudo bem?") is False
    assert is_complex("qual seu nome?") is False
    assert is_complex("") is False


def test_pergunta_curta_simples():
    assert is_complex("que horas são?") is False
    assert is_complex("obrigado!") is False


# ── Sinais decisivos → 14b ───────────────────────────────────────
def test_codigo_colado_escala():
    assert is_complex("o que esse código faz?\n```py\nprint(1)\n```") is True


def test_pergunta_muito_longa_escala():
    assert is_complex("a" * 360) is True


def test_varias_perguntas_escala():
    assert is_complex("o que é X? como usar? quando aplicar? por quê?") is True


# ── Uma pista forte basta (o ganho principal vs heurística antiga) ──
def test_uma_pista_forte_escala():
    # Antes precisava de 2 pistas; agora "otimizar" sozinho (com substância) já escala.
    assert is_complex("como faço para otimizar a performance do meu banco de dados?") is True
    assert is_complex("qual a melhor arquitetura para um sistema de filas distribuído?") is True
    assert is_complex("me explique os trade-offs entre REST e gRPC nesse cenário") is True


def test_pista_forte_em_frase_trivial_nao_escala():
    # "compare" mas frase curtíssima sem substância → não vale o 14b.
    assert is_complex("compare") is False


# ── Acúmulo de pistas suaves ─────────────────────────────────────
def test_duas_pistas_suaves_em_pergunta_longa_escala():
    assert is_complex(
        "por que essa abordagem é melhor e qual a diferença prática entre as duas opções?"
    ) is True


def test_uma_pista_suave_sozinha_nao_escala():
    assert is_complex("por que o céu é azul?") is False
