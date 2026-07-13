"""Testes do retry com backoff e do circuit breaker."""

import time

import pytest

from src.resilience import CircuitBreaker, CircuitOpenError, retry_call


# ── retry_call ───────────────────────────────────────────────────
def test_retry_sucesso_apos_falhas_transitorias():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    assert retry_call(flaky, attempts=3, base_delay=0.001) == "ok"
    assert calls["n"] == 3


def test_retry_esgota_e_repropaga():
    calls = {"n": 0}

    def always():
        calls["n"] += 1
        raise ValueError("x")

    with pytest.raises(ValueError):
        retry_call(always, attempts=2, base_delay=0.001)
    assert calls["n"] == 2


def test_retry_so_pega_excecoes_configuradas():
    def boom():
        raise KeyError("nope")

    # KeyError não está em `exceptions` → não repete, repropaga na hora.
    with pytest.raises(KeyError):
        retry_call(boom, attempts=3, base_delay=0.001, exceptions=(ConnectionError,))


def test_retry_repassa_args_e_kwargs():
    assert retry_call(lambda a, b=0: a + b, 2, b=3, attempts=1) == 5


# ── CircuitBreaker ───────────────────────────────────────────────
def test_breaker_abre_apos_fail_max():
    cb = CircuitBreaker(fail_max=3, reset_after=10, name="t")

    def bad():
        raise ConnectionError("down")

    for _ in range(3):
        with pytest.raises(ConnectionError):
            cb.call(bad)
    assert cb.state == "open"


def test_breaker_rejeita_rapido_quando_aberto():
    cb = CircuitBreaker(fail_max=1, reset_after=10, name="t")
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError()))
    assert cb.state == "open"
    # Agora rejeita sem nem chamar a função.
    sentinel = {"called": False}

    def fn():
        sentinel["called"] = True
        return "x"

    with pytest.raises(CircuitOpenError):
        cb.call(fn)
    assert sentinel["called"] is False


def test_breaker_half_open_recupera_no_sucesso():
    cb = CircuitBreaker(fail_max=1, reset_after=0.05, name="t")
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError()))
    assert cb.state == "open"
    time.sleep(0.06)  # passa o reset_after → half_open
    assert cb.call(lambda: "recovered") == "recovered"
    assert cb.state == "closed"


def test_breaker_half_open_reabre_se_falhar_no_teste():
    cb = CircuitBreaker(fail_max=1, reset_after=0.05, name="t")
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError()))
    time.sleep(0.06)
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError()))
    assert cb.state == "open"  # falhou o teste → reabre


def test_breaker_sucesso_zera_contador():
    cb = CircuitBreaker(fail_max=3, reset_after=10, name="t")
    with pytest.raises(ConnectionError):
        cb.call(lambda: (_ for _ in ()).throw(ConnectionError()))
    cb.call(lambda: "ok")  # sucesso reseta
    assert cb.snapshot()["fails"] == 0
    assert cb.state == "closed"


# ── Integração: knowledge.save não perde conhecimento em falha transitória ──
def _make_kb():
    from src.knowledge import SupabaseKnowledge
    kb = SupabaseKnowledge.__new__(SupabaseKnowledge)
    kb.saved_ok = 0
    kb.save_errors = 0
    kb.last_saved_at = ""
    kb.last_error = ""
    from src.cache import TTLCache
    kb._insights = TTLCache(ttl=120.0)
    kb._insights.set({"total": 1})
    kb._breaker = CircuitBreaker(fail_max=5, reset_after=30, name="supabase-test")
    return kb


def test_save_retenta_e_persiste_apos_falha_transitoria():
    kb = _make_kb()
    state = {"calls": 0}

    class _Q:
        def upsert(self, *a, **k):
            return self

        def execute(self):
            state["calls"] += 1
            if state["calls"] < 2:
                raise ConnectionError("rede instável")
            return type("R", (), {"data": [{}]})()

    kb.client = type("C", (), {"table": lambda self, n: _Q()})()
    kb.save("Título", "https://x/y", "conteúdo")
    assert kb.saved_ok == 1          # persistiu apesar da 1ª falha
    assert state["calls"] == 2       # retentou
    assert kb._insights.get() is None  # invalidou o cache da Mente


def test_save_falha_total_nao_quebra_e_conta_erro():
    kb = _make_kb()

    class _Q:
        def upsert(self, *a, **k):
            return self

        def execute(self):
            raise ConnectionError("fora do ar")

    kb.client = type("C", (), {"table": lambda self, n: _Q()})()
    kb.save("T", "https://x/z", "conteúdo")  # não deve levantar
    assert kb.save_errors == 1
