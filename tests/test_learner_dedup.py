"""Testes do anti-repetição do learner — regressão do bug real em que o
EncyclopediaAgent lotou a fila com 6+ cópias de 'Teoria da relatividade'
(o tópico só vira 'estudado' após o save, e nesse intervalo o fetcher o
re-enfileirava a cada ciclo)."""

import asyncio

import pytest

from src.learner import LearningEngine, LearnedItem


class FakeDB:
    def __init__(self, topics=(), urls=()):
        self.topics = set(topics)
        self.urls = set(urls)

    def is_topic_studied(self, t):
        return t in self.topics

    def is_url_studied(self, u):
        return u in self.urls


@pytest.fixture
def eng():
    return LearningEngine(model="fake-model")


# ── Reserva in-flight ─────────────────────────────────────────────
def test_reserve_bloqueia_duplicata_normalizada(eng):
    assert eng._reserve("Teoria da Relatividade (enciclopédia)")
    # Caixa e espaços diferentes = MESMO tópico → bloqueado.
    assert not eng._reserve("  teoria da  relatividade (enciclopédia) ")
    eng._release("TEORIA DA RELATIVIDADE (ENCICLOPÉDIA)")
    assert eng._reserve("teoria da relatividade (enciclopédia)")


def test_reserve_vazio_nao_reserva(eng):
    assert not eng._reserve("")
    assert not eng._reserve("   ")


def test_start_limpa_inflight(eng):
    # Workers viram no-ops — o teste é só sobre o estado, não sobre a rede.
    async def _noop(*_a, **_k):
        return None
    eng._fetcher = _noop
    eng._summarize_worker = _noop
    eng._save_worker = _noop

    async def run():
        eng._inflight.add("resto de sessao anterior")
        await eng.start()
        leftover = set(eng._inflight)
        await eng.stop()
        return leftover

    assert asyncio.run(run()) == set()


# ── Já estudado (tópico OU URL, todos os agentes) ────────────────
def test_already_known_por_topico_e_url():
    eng = LearningEngine(model="m", db=FakeDB(topics={"Evolução (enciclopédia)"},
                                              urls={"https://pt.wikipedia.org/wiki/DNA"}))
    assert eng._already_known("Evolução (enciclopédia)")
    assert eng._already_known("DNA (enciclopédia)", "https://pt.wikipedia.org/wiki/DNA")
    assert not eng._already_known("Fotossíntese (enciclopédia)")


def test_already_known_sem_db():
    eng = LearningEngine(model="m")
    assert not eng._already_known("qualquer tópico")


# ── Fila nunca recebe duas cópias do mesmo tópico ─────────────────
def test_search_nao_enfileira_copia_do_mesmo_topico(eng, monkeypatch):
    async def fake_research(q, max_results=2):
        return "conteúdo web relevante " * 20, [{"url": "http://fonte"}]
    monkeypatch.setattr("src.learner.web_research", fake_research)

    async def run():
        await eng._fetch_and_enqueue_search("asyncio patterns", "web_search", "web")
        await eng._fetch_and_enqueue_search("asyncio patterns", "web_search", "web")
        await eng._fetch_and_enqueue_search("Asyncio  Patterns", "web_search", "web")
        return eng._fetch_queue.qsize()

    assert asyncio.run(run()) == 1


def test_search_falha_libera_reserva(eng, monkeypatch):
    async def broken_research(q, max_results=2):
        raise RuntimeError("rede fora")
    monkeypatch.setattr("src.learner.web_research", broken_research)

    async def ok_research(q, max_results=2):
        return "conteúdo " * 30, [{"url": "http://fonte"}]

    async def run():
        await eng._fetch_and_enqueue_search("kafka streams", "web_search", "web")
        # A falha NÃO pode deixar o tópico preso no in-flight para sempre.
        monkeypatch.setattr("src.learner.web_research", ok_research)
        await eng._fetch_and_enqueue_search("kafka streams", "web_search", "web")
        return eng._fetch_queue.qsize()

    assert asyncio.run(run()) == 1


def test_save_libera_reserva(eng):
    assert eng._reserve("grpc load balancing")
    item = LearnedItem(topic="grpc load balancing", url="u", summary="s",
                       category="web_search", agent_name="web")
    asyncio.run(eng._save_and_record(item))
    # Depois de salvo, o tópico pode ser reservado de novo (refresh futuro).
    assert eng._reserve("grpc load balancing")
