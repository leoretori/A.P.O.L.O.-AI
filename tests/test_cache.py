"""Testes do utilitário TTLCache compartilhado."""

import time

from src.cache import TTLCache


def test_vazio_retorna_none():
    c = TTLCache(ttl=10)
    assert c.get() is None
    assert c.peek() is None


def test_set_grava_e_devolve():
    c = TTLCache(ttl=10)
    assert c.set({"a": 1}) == {"a": 1}
    assert c.get() == {"a": 1}


def test_get_retorna_mesmo_objeto():
    c = TTLCache(ttl=10)
    obj = object()
    c.set(obj)
    assert c.get() is obj


def test_expira_apos_ttl():
    c = TTLCache(ttl=0.05)
    c.set("x")
    assert c.get() == "x"
    time.sleep(0.06)
    assert c.get() is None       # expirou
    assert c.peek() == "x"       # mas peek devolve o último valor


def test_ttl_zero_sempre_expira():
    c = TTLCache(ttl=0.0)
    c.set("x")
    assert c.get() is None


def test_invalidate_descarta():
    c = TTLCache(ttl=10)
    c.set("x")
    c.invalidate()
    assert c.get() is None
    assert c.peek() is None


def test_peek_nao_renova_validade():
    c = TTLCache(ttl=0.05)
    c.set("x")
    time.sleep(0.06)
    assert c.peek() == "x"
    assert c.get() is None  # peek não revalida
