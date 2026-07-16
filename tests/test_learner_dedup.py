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


# ── Síntese que falha não vira conhecimento ──────────────────────
def _item(topic="tema x", retries=0):
    from src.learner import FetchedItem
    return FetchedItem(topic=topic, url="http://u", content="conteúdo " * 50,
                       category="web_search", agent_name="web", retries=retries)


def test_sintese_falha_reenfileira_uma_vez(eng, monkeypatch):
    async def fail(*a, **k):
        return None
    monkeypatch.setattr(eng, "_summarize", fail)
    eng._reserve("tema x")
    asyncio.run(eng._process_item(_item()))
    # 1ª falha: volta para a fila (com retries=1), reserva mantida.
    assert eng._fetch_queue.qsize() == 1
    assert not eng._reserve("tema x")
    requeued = eng._fetch_queue.get_nowait()
    assert requeued.retries == 1


def test_sintese_falha_2x_desiste_sem_salvar(eng, monkeypatch):
    async def fail(*a, **k):
        return None
    saved = []
    monkeypatch.setattr(eng, "_summarize", fail)
    monkeypatch.setattr(eng, "_persist", lambda item: saved.append(item))
    eng._reserve("tema x")
    asyncio.run(eng._process_item(_item(retries=1)))
    assert eng._fetch_queue.qsize() == 0          # não re-enfileira
    assert saved == []                            # NADA salvo (sem lixo cru)
    assert eng._already_known("tema x")           # desistido nesta sessão
    assert eng._norm("tema x") not in eng._inflight   # reserva liberada


def test_skip_session_limpo_no_start(eng):
    eng._skip_session.add("tema desistido")
    assert eng._already_known("tema desistido")
    eng._skip_session.clear()
    assert not eng._already_known("tema desistido")


def test_prompt_por_categoria():
    from src.learner import SUMMARIZE_PROMPT_GERAL, GENERAL_CATEGORIES
    assert "encyclopedia" in GENERAL_CATEGORIES and "book" in GENERAL_CATEGORIES
    # O template geral não pede código de produção.
    assert "código" not in SUMMARIZE_PROMPT_GERAL.lower().replace("não invente", "")
    assert "Essência" in SUMMARIZE_PROMPT_GERAL


def test_enciclopedia_nao_repete_no_refresh():
    from src.agents.encyclopedia_agent import EncyclopediaAgent, WIKI_SUBJECTS

    class DBTudoEstudado:
        def is_url_studied(self, u):
            return True

    ag = EncyclopediaAgent(model="m", db=DBTudoEstudado())
    t1, _ = asyncio.run(ag.next_topic())
    t2, _ = asyncio.run(ag.next_topic())
    # Mesmo com tudo estudado, o refresh avança na rotação (não trava num só).
    assert t1 != t2
    assert len(WIKI_SUBJECTS) >= 50


# ── Ollama fora do ar: pausa, não descarta ───────────────────────
def test_summarize_detecta_ollama_fora(eng, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("Failed to connect to Ollama")
    monkeypatch.setattr("src.learner.chat_resilient", boom)
    out = asyncio.run(eng._summarize("tema", "conteúdo " * 30))
    assert out is None and eng._llm_down is True


def test_summarize_timeout_nao_e_infra(eng, monkeypatch):
    def slow(*a, **k):
        raise TimeoutError()
    monkeypatch.setattr("src.learner.chat_resilient", slow)
    eng._llm_down = True   # estado anterior qualquer
    out = asyncio.run(eng._summarize("tema", "conteúdo " * 30))
    assert out is None and eng._llm_down is False   # motor vivo, só lento


def test_ollama_fora_pausa_sem_descartar(eng, monkeypatch):
    """REGRESSÃO REAL: com o Ollama desligado, 48 tópicos foram buscados na
    web e descartados um a um. Infraestrutura fora → devolve à fila sem contar
    tentativa e sem entrar no skip da sessão."""
    async def conn_fail(*a, **k):
        eng._llm_down = True
        return None
    monkeypatch.setattr(eng, "_summarize", conn_fail)
    monkeypatch.setattr("src.learner.LLM_DOWN_BACKOFF", 0)
    eng._reserve("tema x")
    asyncio.run(eng._process_item(_item()))
    assert eng._fetch_queue.qsize() == 1
    requeued = eng._fetch_queue.get_nowait()
    assert requeued.retries == 0                     # NÃO contou tentativa
    assert not eng._already_known("tema x")          # NÃO desistiu do tópico
    assert eng._norm("tema x") in eng._inflight      # reserva mantida


def test_ollama_fora_notifica_uma_vez(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    eng2 = LearningEngine(model="m", db=db)

    async def conn_fail(*a, **k):
        eng2._llm_down = True
        return None
    monkeypatch.setattr(eng2, "_summarize", conn_fail)
    monkeypatch.setattr("src.learner.LLM_DOWN_BACKOFF", 0)
    asyncio.run(eng2._process_item(_item("t1")))
    asyncio.run(eng2._process_item(_item("t2")))
    notifs = [n for n in db.list_notifications(20) if "pausado" in n["message"]]
    assert len(notifs) == 1                          # avisa 1×, não spamma


# ── Reparo de sínteses cruas ─────────────────────────────────────
def test_looks_raw():
    eng = LearningEngine(model="m")
    cru = "A teoria da relatividade foi proposta por Einstein " * 10
    sintese = "## Essência\nRelatividade...\n## Pontos-chave\n- tempo é relativo\n" + "x" * 300
    assert eng._looks_raw(cru)
    assert not eng._looks_raw(sintese)
    assert not eng._looks_raw("")          # vazio não é cru
    assert not eng._looks_raw("curto")     # curto demais não vale reparo


def test_repair_resintetiza_e_atualiza_in_place(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    cru = "Texto cru salvo por timeout, sem estrutura nenhuma. " * 12
    db.save_learned_topic("Buraco negro (enciclopédia)", "http://wiki", cru, "encyclopedia")
    db.save_learned_topic("FastAPI async", "http://doc",
                          "## Conceitos-chave\n- ok\n" + "y" * 400, "docs")

    eng = LearningEngine(model="m", db=db)

    async def fake_summarize(topic, content, category="web_search"):
        return f"## Essência\nSíntese reparada de {topic}.\n## Pontos-chave\n- a\n- b" + "z" * 200
    monkeypatch.setattr(eng, "_summarize", fake_summarize)

    res = asyncio.run(eng.repair_raw_summaries(limit=5))
    assert res["ok"] and res["found"] == 1 and res["repaired"] == 1
    rows = {r["topic"]: r["summary"] for r in db.get_learning_history(10)}
    assert "Síntese reparada" in rows["Buraco negro (enciclopédia)"]
    assert rows["FastAPI async"].startswith("## Conceitos")   # intocada


def test_repair_falha_nao_estraga_original(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    cru = "Conteúdo cru de timeout sem seções markdown. " * 12
    db.save_learned_topic("Vulcão (enciclopédia)", "http://wiki", cru, "encyclopedia")
    eng = LearningEngine(model="m", db=db)

    async def fail(*a, **k):
        return None
    monkeypatch.setattr(eng, "_summarize", fail)

    res = asyncio.run(eng.repair_raw_summaries(limit=5))
    assert res["found"] == 1 and res["repaired"] == 0 and res["failed"] == 1
    rows = db.get_learning_history(10)
    assert rows[0]["summary"] == cru[:2000]    # original preservado


def test_get_summary_quality(tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    db.save_learned_topic("a", "u", "## Essência\nsíntese boa " + "x" * 100, "web")
    db.save_learned_topic("b", "u", "texto cru de timeout sem estrutura " * 12, "web")
    db.save_learned_topic("c", "u", "curtinha", "web")
    q = db.get_summary_quality()
    assert q["total"] == 3
    assert q["structured"] == 1 and q["raw"] == 1 and q["short"] == 1
    assert q["pct_structured"] == 33


def test_get_summary_quality_vazia(tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    q = db.get_summary_quality()
    assert q["total"] == 0 and q["pct_structured"] is None


def test_update_topic_summary(tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    db.save_learned_topic("t1", "u", "antiga", "web")
    tid = db.get_learning_history(1)[0]["id"]
    assert db.update_topic_summary(tid, "nova síntese") is True
    assert db.get_learning_history(1)[0]["summary"] == "nova síntese"
    assert db.update_topic_summary(99999, "x") is False


def test_save_libera_reserva(eng):
    assert eng._reserve("grpc load balancing")
    item = LearnedItem(topic="grpc load balancing", url="u", summary="s",
                       category="web_search", agent_name="web")
    asyncio.run(eng._save_and_record(item))
    # Depois de salvo, o tópico pode ser reservado de novo (refresh futuro).
    assert eng._reserve("grpc load balancing")


# ── learn_from_web: pesquisa do Coder vira conhecimento permanente ──
def test_learn_from_web_sintetiza_e_persiste(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    eng = LearningEngine(model="m", db=db)

    async def fake_summarize(topic, content, category="web_search"):
        return f"## Conceitos-chave\n- síntese de {topic}\n" + "z" * 200
    monkeypatch.setattr(eng, "_summarize", fake_summarize)

    content = "Documentação real sobre streaming SSE em FastAPI. " * 8
    ok = asyncio.run(eng.learn_from_web("FastAPI SSE streaming", content))
    assert ok is True
    rows = {r["topic"]: r for r in db.get_learning_history(10)}
    assert "FastAPI SSE streaming" in rows
    assert rows["FastAPI SSE streaming"]["summary"].startswith("## Conceitos")


def test_learn_from_web_conteudo_curto_ignora(tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    eng = LearningEngine(model="m", db=db)
    # Conteúdo < 120 chars não vale síntese (nem chama o LLM).
    ok = asyncio.run(eng.learn_from_web("x", "pouco texto"))
    assert ok is False
    assert db.get_learning_history(10) == []


def test_learn_from_web_ja_estudado_nao_resinteza(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    db.save_learned_topic("asyncio gather", "u", "## já sei\n" + "y" * 200, "web")
    eng = LearningEngine(model="m", db=db)

    called = {"n": 0}
    async def spy_summarize(*a, **k):
        called["n"] += 1
        return "## nova\n" + "z" * 200
    monkeypatch.setattr(eng, "_summarize", spy_summarize)

    ok = asyncio.run(eng.learn_from_web("asyncio gather", "conteúdo novo " * 20))
    assert ok is False           # já estava na base
    assert called["n"] == 0      # nem chamou o LLM (economia)


def test_learn_from_web_falha_sintese_nao_grava(monkeypatch, tmp_path):
    from src.storage import DatabaseManager
    db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db")
    eng = LearningEngine(model="m", db=db)

    async def fail(*a, **k):
        return None              # Ollama fora / timeout
    monkeypatch.setattr(eng, "_summarize", fail)

    ok = asyncio.run(eng.learn_from_web("kafka partições", "conteúdo real " * 20))
    assert ok is False
    assert db.get_learning_history(10) == []   # nada cru salvo


# ── P2.1: amostra de verificação factual (1 em cada VERIFY_SAMPLE_EVERY) ──
async def _drain_pending(coro):
    """`_process_item` dispara `_save_and_record` via create_task (fire-and-
    forget de propósito, evita mais uma fila) — aguarda essa task terminar
    antes do teste inspecionar o resultado."""
    await coro
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


def test_process_item_amostra_1_em_cada_n(eng, monkeypatch):
    async def fake_summarize(*a, **k):
        return "resumo válido " * 10

    verify_calls = []

    async def fake_verify(summary, source):
        verify_calls.append((summary, source))
        return "verified"

    saved = []

    async def fake_save_and_record(item):
        saved.append(item)

    monkeypatch.setattr(eng, "_summarize", fake_summarize)
    monkeypatch.setattr(eng, "_verify_summary", fake_verify)
    monkeypatch.setattr(eng, "_save_and_record", fake_save_and_record)
    monkeypatch.setattr("src.learner.VERIFY_SAMPLE_EVERY", 3)

    async def run():
        for i in range(6):
            await _drain_pending(eng._process_item(_item(f"tema {i}")))

    asyncio.run(run())
    assert len(saved) == 6
    assert [item.verified for item in saved] == \
        [None, None, "verified", None, None, "verified"]
    assert len(verify_calls) == 2   # só 2 dos 6 foram auditados (1 em cada 3)


def test_process_item_verify_falso_nao_impede_o_save(eng, monkeypatch):
    """'failed' na auditoria é um SINAL, não um bloqueio — o resumo ainda é
    salvo (com a marca), não é descartado como se fosse lixo de ingestão."""
    async def fake_summarize(*a, **k):
        return "resumo válido " * 10

    async def fake_verify(summary, source):
        return "failed"

    saved = []

    async def fake_save_and_record(item):
        saved.append(item)

    monkeypatch.setattr(eng, "_summarize", fake_summarize)
    monkeypatch.setattr(eng, "_verify_summary", fake_verify)
    monkeypatch.setattr(eng, "_save_and_record", fake_save_and_record)
    monkeypatch.setattr("src.learner.VERIFY_SAMPLE_EVERY", 1)  # audita sempre

    asyncio.run(_drain_pending(eng._process_item(_item("tema x"))))
    assert len(saved) == 1
    assert saved[0].verified == "failed"


def test_persist_propaga_verified_pro_db_e_pro_rag():
    captured_db, captured_rag = {}, {}

    class _DB:
        def save_learned_topic(self, topic, url, summary, category, verified):
            captured_db["verified"] = verified

    class _Rag:
        def add_example(self, content, doc_id, metadata=None):
            captured_rag["metadata"] = metadata

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng.knowledge_db = None
    eng.rag = _Rag()

    item = LearnedItem(topic="X", url="u", summary="s" * 200,
                       category="web", agent_name="a", verified="verified")
    asyncio.run(eng._persist(item))
    assert captured_db["verified"] == "verified"
    assert captured_rag["metadata"]["verified"] == "verified"


def test_persist_verified_none_vira_unchecked_no_rag():
    """None no dado (maioria — só ~10% é amostrado) não pode virar string
    'None' feia no metadata; a fonte da verdade do rótulo é 'unchecked'."""
    captured_rag = {}

    class _Rag:
        def add_example(self, content, doc_id, metadata=None):
            captured_rag["metadata"] = metadata

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = None
    eng.knowledge_db = None
    eng.rag = _Rag()

    item = LearnedItem(topic="X", url="u", summary="s" * 200,
                       category="web", agent_name="a", verified=None)
    asyncio.run(eng._persist(item))
    assert captured_rag["metadata"]["verified"] == "unchecked"
