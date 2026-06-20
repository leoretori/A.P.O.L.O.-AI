"""Testes das funções puras do learner (auto-currículo)."""

import asyncio

from src.learner import _extract_self_queries, LearningEngine


def test_enqueue_pula_topicos_ja_estudados():
    # Garante que o filtro usa is_topic_studied (correto p/ queries de tópico),
    # não is_url_studied (que nunca casava).
    eng = LearningEngine.__new__(LearningEngine)
    eng._self_queue = asyncio.Queue(maxsize=24)
    eng._next_studies = []

    class _StubDB:
        def is_topic_studied(self, q):
            return "redis" in q.lower()      # finge que já estudou tudo de redis
        def is_url_studied(self, q):
            return False                      # se chamarem o errado, não filtra nada

    eng.db = _StubDB()
    eng._enqueue_self_studies(["redis pub sub patterns", "kafka exactly once"])
    # Só o tópico novo (kafka) deve entrar na fila.
    enfileirados = []
    while not eng._self_queue.empty():
        enfileirados.append(eng._self_queue.get_nowait())
    assert enfileirados == ["kafka exactly once"]


def test_extracts_query_lines():
    s = "texto\n🎯 QUERY: como otimizar índices no postgres\nQUERY: outra pergunta de pesquisa\nlixo"
    r = _extract_self_queries(s)
    assert "como otimizar índices no postgres" in r
    assert len(r) == 2


def test_filters_short_or_no_space():
    assert _extract_self_queries("QUERY: curta") == []        # < 12 chars
    assert _extract_self_queries("QUERY: palavraunicagrande") == []  # sem espaço


def test_dedup_and_limit():
    linhas = ["QUERY: a mesma query longa de pesquisa"] * 3
    linhas += [f"QUERY: query distinta de pesquisa numero {i}" for i in range(8)]
    r = _extract_self_queries("\n".join(linhas))
    assert len(r) <= 6
    assert len(r) == len(set(q.lower() for q in r))  # sem duplicatas


def test_dedup_ignora_pontuacao_e_caixa():
    # "Redis pub/sub patterns" e "redis pub sub patterns?" são o MESMO tema.
    s = "QUERY: Redis pub/sub patterns\nQUERY: redis pub sub patterns?"
    r = _extract_self_queries(s)
    assert len(r) == 1


def test_normaliza_espacos_internos():
    r = _extract_self_queries("QUERY:   como   escalar    filas   distribuídas")
    assert r == ["como escalar filas distribuídas"]
