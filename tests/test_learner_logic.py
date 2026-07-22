"""Testes das funções puras do learner (auto-currículo)."""

import asyncio
import time

import src.learner as learner_mod
from src.learner import _extract_self_queries, _parse_topic_lines, LearningEngine
from src.learner_types import CURRICULUM_RELEVANCE_MIN, FetchedItem, LearnedItem


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


# ── _looks_degenerate (achado real 2026-07-19: loop de degeneração do
# Auto-Currículo — o modelo pequeno inventava palavras tipo "urbanatura") ──
def test_filtra_query_degenerada_com_barra_entre_palavras_longas():
    from src.learner_synthesis import _looks_degenerate

    assert _looks_degenerate("Neurobiologia urburation/urbanatura da arte") is True
    # abreviações reais curtas continuam passando (CI/CD, pub/sub)
    assert _looks_degenerate("CI/CD pipeline best practices") is False
    assert _looks_degenerate("Redis pub/sub patterns production") is False


def test_filtra_query_com_palavra_isolada_absurdamente_longa():
    from src.learner_synthesis import _looks_degenerate

    assert _looks_degenerate("tecnologia urbanaturasensornetourbuacaoextrema real") is True
    assert _looks_degenerate("Kubernetes containerization best practices") is False


def test_extract_self_queries_rejeita_padrao_degenerado_observado():
    s = ("🎯 QUERY: Neurobiologia urburation/urbanatura da arte futura\n"
         "🎯 QUERY: como escalar filas distribuídas em produção")
    r = _extract_self_queries(s)
    assert len(r) == 1
    assert "urburation" not in r[0]


def test_build_synthesis_prompt_exclui_outros_do_contexto():
    """Achado real: mostrar "Outros" de volta ao modelo alimentava o loop de
    degeneração (ele via as próprias invenções e continuava inventando)."""
    from src.learner_synthesis import _build_synthesis_prompt

    clusters = {"Python Core": ["asyncio patterns"],
               "Outros": ["urburation/urbanatura da arte futura"]}
    prompt = _build_synthesis_prompt(clusters)
    assert "asyncio patterns" in prompt
    assert "urburation" not in prompt


# ── item 3 das melhorias de 2026-07-19: rótulos internos ("Síntese #N") não
# voltam pro contexto do modelo — ele via os próprios números e confundia com
# um tema real, gerando placeholders tipo "(ou qualquer síndrome específica)" ──
def test_cluster_topics_exclui_categoria_synthesis():
    from src.learner_synthesis import _cluster_topics

    history = [
        {"topic": "asyncio patterns", "summary": "python async", "category": "web_search"},
        {"topic": "Síntese #23", "summary": "cross-domain", "category": "synthesis"},
    ]
    clusters = _cluster_topics(history)
    all_topics = [t for topics in clusters.values() for t in topics]
    assert "Síntese #23" not in all_topics
    assert any("asyncio" in t for t in all_topics)


def test_looks_degenerate_pega_placeholder_meta_deixado_pelo_modelo():
    from src.learner_synthesis import _looks_degenerate

    assert _looks_degenerate("Síntese #24 (ou qualquer síndrome específica)") is True
    assert _looks_degenerate("Próximos estudos (não mencionado)") is True
    assert _looks_degenerate("Como escalar filas distribuídas em produção") is False


def test_persist_nao_trava_com_save_lento(monkeypatch):
    """Regressão do 'estudou 45 e travou': uma escrita lenta (Supabase em rede
    ruim) NÃO pode segurar o _persist. Com PERSIST_TIMEOUT curto, ele desiste e
    segue — em vez de pendurar o pipeline (e esgotar o pool de threads)."""
    monkeypatch.setattr(learner_mod, "PERSIST_TIMEOUT", 0.2)

    class _SlowKnowledge:
        def save(self, *a, **k):
            time.sleep(1.0)          # simula Supabase pendurado (bloqueia a thread)

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = None
    eng.knowledge_db = _SlowKnowledge()
    eng.rag = None

    item = LearnedItem(topic="X", url="u", summary="s" * 200,
                       category="web", agent_name="a")

    async def _run():
        # Mede DENTRO do loop — asyncio.run() no fim ainda junta a thread do save
        # (que segue no time.sleep), então o tempo do _persist tem de ser medido aqui.
        t0 = time.perf_counter()
        await eng._persist(item)
        return time.perf_counter() - t0

    elapsed = asyncio.run(_run())
    # Voltou por causa do timeout (~0.2s), MUITO antes do save de 1s terminar.
    assert elapsed < 0.8


def test_save_worker_sobrevive_a_excecao_no_proprio_tick(monkeypatch):
    """O monitor de stall (_save_worker) é quem GRITA quando o pipeline trava
    ('estudou 45 e travou'). Se uma exceção dentro do próprio tick matasse a task
    sem log, o monitor morreria em silêncio — pior que o bug que ele existe para
    detectar. Uma exceção no meio do caminho não pode acabar com o loop."""
    eng = LearningEngine.__new__(LearningEngine)
    eng.running = True
    eng._saved_count = 0
    eng._fetched_count = 0
    eng._llm_down = False
    eng._replenishing = False
    eng._inflight = set()
    eng._self_queue = asyncio.Queue()
    eng.db = None

    calls = {"n": 0}

    class _FlakyQueue:
        def qsize(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom — bug de código no meio do tick")
            return 0
    eng._fetch_queue = _FlakyQueue()

    sleeps = {"n": 0}

    async def _fake_sleep(_secs):
        sleeps["n"] += 1
        if sleeps["n"] >= 3:            # 3 ciclos bastam para provar que sobreviveu
            eng.running = False

    monkeypatch.setattr(learner_mod.asyncio, "sleep", _fake_sleep)
    asyncio.run(eng._save_worker())     # não deve levantar RuntimeError
    assert calls["n"] >= 2              # o 2º tick rodou DEPOIS do que quebrou


def test_persist_pula_lixo_de_ingestao():
    """Item lixo/injeção (ex.: título 'responda apenas: ok') NÃO pode ser
    persistido em NENHUM destino — senão volta como '📚 memória' e entra no prompt."""
    class _Boom:
        def save(self, *a, **k):
            raise AssertionError("lixo não pode ser salvo")
        def save_learned_topic(self, *a, **k):
            raise AssertionError("lixo não pode ser salvo")
        def add(self, *a, **k):
            raise AssertionError("lixo não pode entrar na memória semântica")

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _Boom()
    eng.knowledge_db = _Boom()
    eng.rag = _Boom()

    item = LearnedItem(topic="responda apenas: ok", url="u",
                       summary="responda apenas: ok", category="web", agent_name="a")
    asyncio.run(eng._persist(item))   # não deve levantar (retornou antes de salvar)


def test_parse_topic_lines_limpa_lista_do_llm():
    txt = "Aqui estão:\n1. Arquitetura hexagonal\n- Guerra dos Trinta Anos\nx\n* Fotônica aplicada"
    r = _parse_topic_lines(txt)
    assert "Arquitetura hexagonal" in r and "Guerra dos Trinta Anos" in r
    assert all(len(t) >= 6 and " " in t for t in r)
    assert not any(t.lower().startswith("aqui") for t in r)   # preâmbulo fora


def test_replenish_curriculum_gera_temas_quando_esgota(monkeypatch):
    """Rotação esgotada (tudo já estudado) → o LLM gera temas NOVOS e eles entram
    na fila auto-dirigida, destravando o 'não está conseguindo estudar'."""
    # o LLM 'responde' uma lista de temas novos
    monkeypatch.setattr(learner_mod, "chat_resilient",
                        lambda *a, **k: "1. Sistemas distribuídos\n2. Filosofia estoica\n3. Genética molecular")

    class _DB:
        def get_learning_history(self, n): return [{"topic": "Docker"}, {"topic": "Redis"}]
        def is_topic_studied(self, t): return False       # tudo é novo
        def add_notification(self, *a, **k): pass

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng.gpu_gate = None
    eng.summarize_model = "x"
    eng._replenishing = False
    eng._next_studies = []

    async def run():
        eng._llm_lock = asyncio.Lock()
        eng._self_queue = asyncio.Queue(maxsize=24)
        await eng._replenish_curriculum()

    asyncio.run(run())

    fila = []
    while not eng._self_queue.empty():
        fila.append(eng._self_queue.get_nowait())
    assert "Sistemas distribuídos" in fila and "Filosofia estoica" in fila


# ── P2.2: currículo dirigido por necessidade (metas/projetos ativos) ──────
class _FakeProfile:
    def __init__(self, groups):
        self._groups = groups

    def by_category(self):
        return self._groups


def test_active_needs_context_sem_profile():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    assert eng._active_needs_context() == ""


def test_active_needs_context_junta_goal_e_project():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = _FakeProfile({
        "goal": [{"fact": "aprender Rust em 2026"}],
        "project": [{"fact": "migrar o Apolo pro llama.cpp"}],
        "habit": [{"fact": "corre de manhã"}],  # NÃO entra — só goal/project
    })
    ctx = eng._active_needs_context()
    assert "aprender Rust em 2026" in ctx
    assert "migrar o Apolo pro llama.cpp" in ctx
    assert "corre de manhã" not in ctx


def test_active_needs_context_profile_quebrado_nao_derruba():
    class _Boom:
        def by_category(self):
            raise RuntimeError("json corrompido")
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = _Boom()
    assert eng._active_needs_context() == ""


def test_replenish_curriculum_ancora_no_perfil_quando_ha_metas(monkeypatch):
    """Com metas/projetos ativos, o prompt PRIORIZA eles — a diferença real
    entre 'currículo por novidade' e 'currículo por necessidade' (P2.2)."""
    captured = {}

    def fake_chat(model, messages, **k):
        captured["prompt"] = messages[0]["content"]
        return "1. Tópico relacionado\n2. Outro tópico"
    monkeypatch.setattr(learner_mod, "chat_resilient", fake_chat)

    class _DB:
        def get_learning_history(self, n): return [{"topic": "Docker"}]
        def is_topic_studied(self, t): return False
        def add_notification(self, *a, **k): pass

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng.gpu_gate = None
    eng.summarize_model = "x"
    eng._replenishing = False
    eng._next_studies = []
    eng.profile = _FakeProfile({"goal": [{"fact": "aprender Rust em 2026"}]})

    async def run():
        eng._llm_lock = asyncio.Lock()
        eng._self_queue = asyncio.Queue(maxsize=24)
        await eng._replenish_curriculum()

    asyncio.run(run())
    assert "aprender Rust em 2026" in captured["prompt"]
    assert "PRIORIZE" in captured["prompt"]


def test_replenish_curriculum_sem_metas_usa_exploracao_geral(monkeypatch):
    """Sem perfil/metas, o comportamento é o de sempre (só novidade) — P2.2
    não quebra quem nunca preencheu o modelo pessoal."""
    captured = {}

    def fake_chat(model, messages, **k):
        captured["prompt"] = messages[0]["content"]
        return "1. Tópico qualquer"
    monkeypatch.setattr(learner_mod, "chat_resilient", fake_chat)

    class _DB:
        def get_learning_history(self, n): return [{"topic": "Docker"}]
        def is_topic_studied(self, t): return False
        def add_notification(self, *a, **k): pass

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = _DB()
    eng.gpu_gate = None
    eng.summarize_model = "x"
    eng._replenishing = False
    eng._next_studies = []
    eng.profile = None

    async def run():
        eng._llm_lock = asyncio.Lock()
        eng._self_queue = asyncio.Queue(maxsize=24)
        await eng._replenish_curriculum()

    asyncio.run(run())
    assert "PRIORIZE" not in captured["prompt"]
    assert "Misture tecnologia e conhecimento geral" in captured["prompt"]


# ── P2.3: filtro de deriva do currículo ────────────────────────────────
def test_curriculum_too_verbose_bate_os_exemplos_reais():
    """Os exemplos REAIS de deriva vistos em produção (2026-07-15) têm que
    cair no filtro; os tópicos legítimos medidos não podem ser pegos."""
    eng = LearningEngine
    derivados = [
        "Otimização de infraestruturas urbanas inteligentes com Machine Learning",
        "Desenvolvimento e implementação da IA aplicada à gestão das águas "
        "potáveis urbanas resilientes",
    ]
    legitimos = ["Filosofia estoica", "Sistemas distribuídos", "Genética molecular",
                "Async no FastAPI"]
    assert all(eng._curriculum_too_verbose(t) for t in derivados)
    assert not any(eng._curriculum_too_verbose(t) for t in legitimos)


def test_interest_corpus_sem_perfil_fica_vazio():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    eng.db = None
    assert eng._interest_corpus() == ""


def test_interest_corpus_ignora_historico_de_proposito():
    """Regressão da 1ª tentativa (descartada): histórico de tópicos já
    estudados NÃO entra no corpus — usá-lo rejeitava diversidade legítima."""
    class _DB:
        def get_learning_history(self, n):
            raise AssertionError("o corpus de interesse não deve consultar o histórico")
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    eng.db = _DB()
    assert eng._interest_corpus() == ""   # nem chega a chamar o histórico


def test_curriculum_relevance_sem_corpus_nao_filtra():
    eng = LearningEngine.__new__(LearningEngine)
    assert eng._curriculum_relevance("qualquer tópico aqui", "") == 1.0


def test_curriculum_relevance_topico_conectado_ao_perfil():
    eng = LearningEngine.__new__(LearningEngine)
    corpus = "aprender rust em 2026 migrar apolo pro llama cpp"
    alta = eng._curriculum_relevance("Ownership e borrow checker em Rust", corpus)
    baixa = eng._curriculum_relevance("Culinária francesa clássica", corpus)
    assert alta > baixa
    assert baixa < CURRICULUM_RELEVANCE_MIN


def test_enqueue_self_studies_descarta_topico_verboso(monkeypatch):
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    eng.db = None
    eng._self_queue = asyncio.Queue(maxsize=24)
    eng._next_studies = []
    eng._enqueue_self_studies([
        "Otimização de infraestruturas urbanas inteligentes com Machine Learning",
        "Filosofia estoica",
    ])
    fila = []
    while not eng._self_queue.empty():
        fila.append(eng._self_queue.get_nowait())
    assert fila == ["Filosofia estoica"]


def test_enqueue_self_studies_descarta_topico_fora_do_perfil(monkeypatch):
    """Com metas/projetos preenchidos, um tópico sem NENHUMA conexão é
    descartado — o próprio caso de uso que o item pede."""
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = _FakeProfile({"goal": [{"fact": "aprender Rust em 2026"}]})
    eng.db = None
    eng._self_queue = asyncio.Queue(maxsize=24)
    eng._next_studies = []
    eng._enqueue_self_studies(["Culinária francesa clássica", "Rust ownership básico"])
    fila = []
    while not eng._self_queue.empty():
        fila.append(eng._self_queue.get_nowait())
    assert fila == ["Rust ownership básico"]


# ── P2.7: re-verificação priorizada ────────────────────────────────────
def test_effective_relearn_days_setor_volatil_encurta():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    dias = eng._effective_relearn_days("guia rápido de Kubernetes na AWS")
    assert dias < 21   # RELEARN_DAYS padrão do storage_models


def test_effective_relearn_days_setor_estavel_usa_padrao():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    assert eng._effective_relearn_days("Introdução à física quântica") == 21


def test_effective_relearn_days_ligado_a_meta_ativa_encurta_mais():
    """O tópico bate com uma meta ativa do perfil → janela some pra metade,
    além do que o setor já daria — o caso de uso real do item."""
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = _FakeProfile({"goal": [{"fact": "aprender Rust ownership e borrow checker"}]})
    sem_meta = LearningEngine.__new__(LearningEngine)
    sem_meta.profile = None

    com = eng._effective_relearn_days("Rust ownership básico")
    sem = sem_meta._effective_relearn_days("Rust ownership básico")
    assert com < sem


def test_effective_relearn_days_piso_de_3_dias():
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = _FakeProfile({"goal": [{"fact": "aprender Kubernetes AWS"}]})
    # setor volátil (10d) cortado pela metade (5d) — ainda acima do piso, mas
    # prova que o piso existe e não deixa a janela sumir de vez.
    assert eng._effective_relearn_days("guia rápido de Kubernetes na AWS") >= 3


def test_effective_relearn_days_desligado_fica_desligado(monkeypatch):
    import src.storage_models as sm_mod
    monkeypatch.setattr(sm_mod, "RELEARN_DAYS", 0)
    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    assert eng._effective_relearn_days("qualquer tópico de kubernetes") == 0


def test_already_known_usa_janela_efetiva(monkeypatch):
    chamado = {}

    class _DB:
        def is_topic_studied(self, topic, relearn_days=None):
            chamado["relearn_days"] = relearn_days
            return False

    eng = LearningEngine.__new__(LearningEngine)
    eng.profile = None
    eng.db = _DB()
    eng._skip_session = set()
    eng._already_known_sync("guia rápido de Kubernetes na AWS")
    assert chamado["relearn_days"] == eng._effective_relearn_days("guia rápido de Kubernetes na AWS")
    assert chamado["relearn_days"] < 21


def test_llm_lock_serializa_inferencias(monkeypatch):
    """Regressão do 'estudou muito e travou de vez': o lock impede que summarize
    (3b) e síntese (14b) infiram AO MESMO TEMPO — numa 16GB CPU-only isso travava
    tudo (thrash) e todo tópico estourava o timeout. Nunca >1 inferência simultânea."""
    import threading
    state = {"cur": 0, "max": 0}
    guard = threading.Lock()

    def fake(model, messages, **k):
        with guard:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        time.sleep(0.1)
        with guard:
            state["cur"] -= 1
        return "x" * 100

    monkeypatch.setattr(learner_mod, "chat_resilient", fake)

    eng = LearningEngine.__new__(LearningEngine)
    eng.gpu_gate = None
    eng.summarize_model = "m"
    eng._llm_down = False
    eng._llm_down_notified = False

    async def run():
        eng._llm_lock = asyncio.Lock()           # liga ao loop em execução
        await asyncio.gather(*[
            eng._summarize(f"t{i}", "conteúdo suficientemente longo " * 20, "web")
            for i in range(4)
        ])

    asyncio.run(run())
    assert state["max"] == 1                      # nunca 2 inferências ao mesmo tempo


def test_summarize_worker_sobrevive_a_erro_no_process():
    """Blindagem contra o 'travou e não conseguiu mais': se _process_item lança,
    o worker NÃO pode morrer (senão a fila lota e os fetchers congelam). Ele
    solta o item do in-flight e segue para o próximo."""
    eng = LearningEngine.__new__(LearningEngine)
    eng.running = True
    eng._fetch_queue = asyncio.Queue(maxsize=12)
    eng._inflight = {"x"}
    calls = {"n": 0}

    async def boom(item):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("explodiu no 1º item")
        eng.running = False           # 2º item: encerra o loop de forma limpa

    eng._process_item = boom

    async def run():
        eng._fetch_queue.put_nowait(FetchedItem("x", "u", "c" * 200, "web", "a"))
        eng._fetch_queue.put_nowait(FetchedItem("y", "u", "c" * 200, "web", "a"))
        await asyncio.wait_for(eng._summarize_worker(), timeout=5)

    asyncio.run(run())
    assert calls["n"] == 2                 # sobreviveu ao 1º erro e processou o 2º
    assert "x" not in eng._inflight        # release após o erro


def test_normaliza_espacos_internos():
    r = _extract_self_queries("QUERY:   como   escalar    filas   distribuídas")
    assert r == ["como escalar filas distribuídas"]


# ── E8: tasks de fundo com referência forte e exceção visível ────────────
def test_spawn_mantem_referencia_forte_e_limpa_no_fim():
    """Sem referência forte, o event loop guarda só uma FRACA e o GC pode
    coletar a task no meio do save (E8)."""
    async def cenario():
        eng = LearningEngine.__new__(LearningEngine)
        eng._bg_tasks = set()
        começou = asyncio.Event()

        async def trabalho():
            começou.set()
            await asyncio.sleep(0.01)
            return "feito"

        t = eng._spawn(trabalho(), name="teste")
        await começou.wait()
        assert t in eng._bg_tasks          # referência viva enquanto roda
        import gc
        gc.collect()                        # o GC não pode levar a task embora
        assert await t == "feito"
        await asyncio.sleep(0)              # deixa o callback rodar
        assert eng._bg_tasks == set()       # e some quando termina

    asyncio.run(cenario())


def test_spawn_loga_excecao_da_task(caplog):
    """Exceção em task solta some como 'Task exception was never retrieved' no
    stderr; aqui ela vai para o logger da app, com o nome da task."""
    async def cenario():
        eng = LearningEngine.__new__(LearningEngine)
        eng._bg_tasks = set()

        async def explode():
            raise RuntimeError("o save falhou feio")

        t = eng._spawn(explode(), name="save-and-record")
        await asyncio.gather(t, return_exceptions=True)
        await asyncio.sleep(0)

    with caplog.at_level("WARNING"):
        asyncio.run(cenario())
    assert any("save-and-record" in r.message and "o save falhou feio" in r.message
               for r in caplog.records)


def test_spawn_ignora_cancelamento():
    """Cancelar não é falha — não deve poluir o log nem levantar."""
    async def cenario():
        eng = LearningEngine.__new__(LearningEngine)
        eng._bg_tasks = set()
        t = eng._spawn(asyncio.sleep(5), name="longa")
        await asyncio.sleep(0)
        t.cancel()
        await asyncio.gather(t, return_exceptions=True)
        await asyncio.sleep(0)
        assert eng._bg_tasks == set()

    asyncio.run(cenario())


# ── E9: reparo de sínteses não pode virar moto-perpétuo ──────────────────
def test_looks_raw_aceita_sintese_sem_cabecalho():
    """O 1.5B escreve sínteses válidas SEM '##' — marcá-las como cruas para
    sempre gastava 1 chamada de LLM por rodada, para sempre (E9)."""
    eng = LearningEngine.__new__(LearningEngine)
    corrido = "texto corrido sem nenhuma estrutura. " * 20
    assert eng._looks_raw(corrido)                       # isto SIM é cru

    com_lista = "Resumo do tema:\n- ponto um aqui\n- ponto dois aqui\n" + corrido
    assert not eng._looks_raw(com_lista)
    com_negrito = "**Conceito:** " + corrido
    assert not eng._looks_raw(com_negrito)
    varios_paragrafos = corrido[:200] + "\n\n" + corrido[:200] + "\n\n" + corrido[:200]
    assert not eng._looks_raw(varios_paragrafos)
    assert not eng._looks_raw("curto demais para julgar")
    assert not eng._looks_raw("## Conceitos\n" + corrido)


def test_reparo_desiste_depois_de_n_tentativas(tmp_path, monkeypatch):
    import src.learner as learner_mod

    monkeypatch.setattr(learner_mod, "MAX_REPAIR_TRIES", 2)

    eng = LearningEngine.__new__(LearningEngine)
    eng.repair_ledger = str(tmp_path / "repair.jsonl")
    assert eng._repair_giveups() == set()

    eng._record_repair_attempt(42, "tema teimoso")
    assert eng._repair_giveups() == set()                 # 1 falha: ainda tenta
    eng._record_repair_attempt(42, "tema teimoso")
    assert eng._repair_giveups() == {eng._repair_key(42, "tema teimoso")}


def test_reparo_pula_os_desistidos(tmp_path, monkeypatch):
    """Item que falhou o bastante sai da fila — não gasta LLM de novo."""
    import src.learner as learner_mod

    monkeypatch.setattr(learner_mod, "MAX_REPAIR_TRIES", 1)

    cru = "texto corrido sem estrutura nenhuma. " * 20
    eng = LearningEngine.__new__(LearningEngine)
    eng.repair_ledger = str(tmp_path / "repair.jsonl")
    eng.db = type("_DB", (), {
        "get_learning_history": lambda self, n: [
            {"id": 1, "topic": "teimoso", "summary": cru, "category": "docs"},
            {"id": 2, "topic": "novo", "summary": cru, "category": "docs"},
        ],
        "add_notification": lambda self, *a, **k: None,
        "update_topic_summary": lambda self, *a, **k: None,
    })()
    eng.rag = None
    tentados = []

    async def _fake_summarize(topic, content, category):
        tentados.append(topic)
        return None                                       # falha sempre

    eng._summarize = _fake_summarize
    eng._record_repair_attempt(1, "teimoso")              # já desistido

    res = asyncio.run(eng.repair_raw_summaries(limit=5))
    assert res["found"] == 1 and tentados == ["novo"]


# ── E22/E23: contadores e dedup consistentes em TODOS os caminhos ────────
def test_maybe_synthesize_dispara_no_marco(monkeypatch):
    import src.learner as learner_mod

    monkeypatch.setattr(learner_mod, "SYNTHESIS_EVERY", 3)
    eng = LearningEngine.__new__(LearningEngine)
    disparos = []
    eng._spawn = lambda coro, name: (coro.close(), disparos.append(name))[1]

    for n in (1, 2, 3, 4, 5, 6):
        eng._saved_count = n
        eng._maybe_synthesize()
    assert disparos == ["deep-synthesis", "deep-synthesis"]   # nos passos 3 e 6


def test_maybe_synthesize_ignora_contador_zero():
    eng = LearningEngine.__new__(LearningEngine)
    eng._saved_count = 0
    eng._spawn = lambda coro, name: pytest_fail_spawn()

    def pytest_fail_spawn():
        raise AssertionError("não devia sintetizar com 0 salvos")

    eng._maybe_synthesize()
