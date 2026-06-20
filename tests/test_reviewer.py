"""Testes da detecção de linguagem do Code Review."""

from src.reviewer import detect_language


def test_python():
    assert detect_language("def soma(a, b):\n    return a + b") == "python"


def test_sql():
    assert detect_language("SELECT id, nome FROM usuarios WHERE id = 1") == "sql"


def test_go():
    assert detect_language("package main\n\nfunc main() {\n    println(\"oi\")\n}") == "go"


def test_rust():
    assert detect_language("fn main() {\n    let mut total = 0;\n}") == "rust"


def test_javascript():
    assert detect_language("const f = () => { console.log(1); }") == "javascript"
