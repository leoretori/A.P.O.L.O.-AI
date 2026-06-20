"""Testes dos helpers."""

from src.utils import extract_code, sanitize_request


def test_extrai_bloco_python():
    text = "Aqui está o código:\n```python\nprint('oi')\n```"
    assert extract_code(text) == "print('oi')"


def test_extrai_bloco_generico():
    text = "```\nprint('oi')\n```"
    assert extract_code(text) == "print('oi')"


def test_retorna_texto_sem_bloco():
    text = "print('oi')"
    assert extract_code(text) == "print('oi')"


def test_sanitize_trunca():
    long_req = "x" * 3000
    assert len(sanitize_request(long_req)) == 2000


def test_sanitize_strip():
    assert sanitize_request("  pedido  ") == "pedido"
