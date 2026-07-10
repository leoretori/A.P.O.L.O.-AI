"""Testes que travam as otimizações de performance (caches + telemetria).

Não dependem de Supabase/Ollama reais — usam stubs/objetos crus — então rodam
rápido e em CI. Garantem que uma regressão (ex.: cache removido sem querer) seja
pega cedo.
"""


from src.knowledge import SupabaseKnowledge
from src.telemetry import LatencyTracker
from src.topics import classify_sector


# ── classify_sector tem lru_cache ────────────────────────────────
def test_classify_sector_eh_cacheado():
    # A função deve expor a interface do lru_cache.
    assert hasattr(classify_sector, "cache_info")
    classify_sector.cache_clear()
    classify_sector("kubernetes operators")
    classify_sector("kubernetes operators")
    info = classify_sector.cache_info()
    assert info.hits >= 1  # 2ª chamada idêntica veio do cache
    assert info.misses == 1


def test_classify_sector_determinismo_preservado():
    classify_sector.cache_clear()
    a = classify_sector("react server components")
    b = classify_sector("react server components")
    assert a == b
    assert isinstance(a, str) and a


# ── insights() tem cache TTL invalidado por save ─────────────────
class _FakeResp:
    def __init__(self, rows, count):
        self.data = rows
        self.count = count


class _FakeTable:
    def __init__(self, counter):
        self._c = counter

    def select(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        self._c["n"] += 1
        return _FakeResp(
            [{"title": "Redis pub sub", "url": "https://redis.io/x",
              "category": "web", "tags": ["infra"],
              "updated_at": "2026-06-01T00:00:00Z"}],
            1,
        )


def _make_kb():
    from src.resilience import CircuitBreaker
    from src.cache import TTLCache
    kb = SupabaseKnowledge.__new__(SupabaseKnowledge)
    kb._insights = TTLCache(ttl=120.0)
    kb._breaker = CircuitBreaker(name="test")
    counter = {"n": 0}
    kb.client = type("C", (), {"table": lambda self, name: _FakeTable(counter)})()
    return kb, counter


def test_insights_usa_cache_na_segunda_chamada():
    kb, counter = _make_kb()
    r1 = kb.insights()
    r2 = kb.insights()
    assert counter["n"] == 1          # só uma query ao Supabase
    assert r1 is r2                   # mesmo objeto cacheado
    assert r1["total"] == 1


def test_insights_invalida_cache_apos_save_simulado():
    kb, counter = _make_kb()
    kb.insights()
    assert counter["n"] == 1
    kb._insights.invalidate()         # o que save() faz ao gravar conhecimento
    kb.insights()
    assert counter["n"] == 2          # recalculou


def test_insights_respeita_ttl_expirado():
    kb, counter = _make_kb()
    kb._insights.ttl = 0.0           # tudo expira imediatamente
    kb.insights()
    kb.insights()
    assert counter["n"] == 2


# ── stats() não baixa todas as linhas (limit aplicado) ───────────
def test_stats_aplica_limit_para_so_contar():
    captured = {"limit": None}

    class _StatsTable:
        def select(self, *a, **k):
            return self

        def limit(self, n):
            captured["limit"] = n
            return self

        def execute(self):
            return _FakeResp([{"id": 1}], 4242)

    from src.resilience import CircuitBreaker
    kb = SupabaseKnowledge.__new__(SupabaseKnowledge)
    kb.saved_ok = 0
    kb.save_errors = 0
    kb.last_saved_at = ""
    kb.last_error = ""
    kb._breaker = CircuitBreaker(name="test")
    kb.client = type("C", (), {"table": lambda self, name: _StatsTable()})()
    out = kb.stats()
    assert out["total"] == 4242
    assert captured["limit"] == 1     # leu só o contador, não a tabela inteira


# ── LatencyTracker ───────────────────────────────────────────────
def test_tracker_agrega_media_e_p95():
    t = LatencyTracker()
    for ms in [10, 20, 30, 40, 100]:
        t.record("/api/health", ms)
    snap = t.snapshot()
    row = next(r for r in snap["routes"] if r["route"] == "/api/health")
    assert row["count"] == 5
    assert row["avg_ms"] == 40.0
    assert row["max_ms"] == 100
    assert row["p95_ms"] >= 40
    assert snap["total_requests"] == 5


def test_tracker_conta_erros_e_slowest():
    t = LatencyTracker()
    t.record("/api/x", 5, is_error=True)
    t.record("/api/y", 500)
    snap = t.snapshot()
    xrow = next(r for r in snap["routes"] if r["route"] == "/api/x")
    assert xrow["errors"] == 1
    assert snap["slowest"]["route"] == "/api/y"
    assert snap["slowest"]["ms"] == 500


def test_tracker_reset_zera_tudo():
    t = LatencyTracker()
    t.record("/api/z", 1)
    t.reset()
    snap = t.snapshot()
    assert snap["total_requests"] == 0
    assert snap["routes"] == []


def test_tracker_ordena_por_media_desc():
    t = LatencyTracker()
    t.record("/api/fast", 5)
    t.record("/api/slow", 900)
    routes = t.snapshot()["routes"]
    assert routes[0]["route"] == "/api/slow"
