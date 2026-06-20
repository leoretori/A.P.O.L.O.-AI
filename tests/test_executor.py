"""Testes do executor de código."""

import pytest
from src.executor import CodeExecutor


@pytest.fixture
def executor():
    return CodeExecutor(timeout=10)


def test_executa_codigo_simples(executor):
    result = executor.run("print('hello')")
    assert result.success
    assert "hello" in result.stdout


def test_captura_erro_de_sintaxe(executor):
    result = executor.run("def broken(")
    assert not result.success
    assert result.stderr


def test_timeout(executor):
    executor.timeout = 1
    result = executor.run("import time; time.sleep(10)")
    assert not result.success
    assert "Timeout" in result.stderr


def test_codigo_com_excecao(executor):
    result = executor.run("raise ValueError('erro teste')")
    assert not result.success
    assert "ValueError" in result.stderr
