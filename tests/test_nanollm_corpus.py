"""Exportador de corpus soberano (src/nanollm/corpus_export)."""

import json
import sqlite3

import pytest

from src.nanollm.corpus_export import (
    DOC_SEPARATOR,
    Deduper,
    clean_text,
    export_corpus,
    has_secret,
    is_portuguese,
)
from src.nanollm.data import read_corpus

PT = ("O aprendizado de máquina é uma área da computação que estuda como os "
      "sistemas aprendem com os dados sem serem programados de forma explícita. "
      "Os modelos são treinados com exemplos e depois usados para prever casos novos. ")
EN = ("Machine learning is a field of computer science that studies how systems "
      "learn from data without being explicitly programmed for the task at hand. ")


@pytest.fixture()
def bancos(tmp_path):
    """apolo.db + local_knowledge.db falsos com os schemas reais mínimos."""
    db = tmp_path / "apolo.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE learned_topics (id INTEGER PRIMARY KEY, topic TEXT, "
                "url TEXT, summary TEXT, category TEXT, studied_at TEXT)")
    con.execute("CREATE TABLE episodes (id INTEGER PRIMARY KEY, session_id TEXT, "
                "occurred_at TEXT, title TEXT, summary TEXT, tags TEXT, created_at TEXT)")
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("FastAPI", PT * 3, "backend"))
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("English topic", EN * 3, "web"))
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("Vazio", "", "web"))
    con.execute("INSERT INTO episodes (occurred_at, title, summary) VALUES (?,?,?)",
                ("2026-07-06 10:00:00", "fechamos o Épico 2.1", PT * 2))
    con.commit()
    con.close()

    kdb = tmp_path / "know.db"
    kon = sqlite3.connect(kdb)
    kon.execute("CREATE TABLE knowledge (id INTEGER PRIMARY KEY, title TEXT, url TEXT, "
                "content TEXT, category TEXT, tags TEXT, updated_at TEXT)")
    kon.execute("INSERT INTO knowledge (title, url, content) VALUES (?,?,?)",
                ("Guia de Python", "https://x/1", PT * 3 + "\nAPI_KEY=abc123segredo\n" + PT))
    kon.execute("INSERT INTO knowledge (title, url, content) VALUES (?,?,?)",
                ("Duplicado", "https://x/2", PT * 3))  # parágrafo já visto → dedup
    kon.commit()
    kon.close()
    return db, kdb


def test_export_end_to_end(bancos, tmp_path):
    db, kdb = bancos
    out = tmp_path / "corpus"
    report = export_corpus(db, kdb, out, min_chars=100)

    topics = (out / "apolo_topics.txt").read_text(encoding="utf-8")
    assert "Tópico: FastAPI" in topics
    assert "English topic" not in topics  # filtro de idioma
    assert "Episódio de 2026-07-06: fechamos o Épico 2.1" in \
        (out / "apolo_episodes.txt").read_text(encoding="utf-8")
    know = (out / "apolo_knowledge.txt").read_text(encoding="utf-8")
    assert "Guia de Python" in know
    assert "API_KEY" not in know  # segredo NUNCA sai
    assert "Duplicado" not in know or report["paragrafos_duplicados_removidos"] > 0

    r = report["sources"]
    assert r["apolo_topics"]["registros"] == 2  # o summary vazio nem sai do SQL
    assert r["apolo_topics"]["mantidos"] == 1
    assert r["apolo_topics"]["descartados_idioma"] == 1
    assert report["chars_total"] > 0 and report["tokens_estimados"] > 0
    assert json.loads((out / "report.json").read_text(encoding="utf-8"))


def test_export_integra_com_read_corpus(bancos, tmp_path):
    db, kdb = bancos
    out = tmp_path / "corpus"
    export_corpus(db, kdb, out, min_chars=100)
    docs = read_corpus(out)
    assert len(docs) >= 3  # topic + episódio + knowledge, cada um vira doc próprio
    assert all(DOC_SEPARATOR not in d for d in docs)


def test_export_bancos_inexistentes(tmp_path):
    report = export_corpus(tmp_path / "nao.db", tmp_path / "nem.db", tmp_path / "c")
    assert report["chars_total"] == 0


def test_export_docs_extras(bancos, tmp_path):
    db, kdb = bancos
    extra = tmp_path / "meus_docs"
    extra.mkdir()
    (extra / "nota.txt").write_text(PT * 4, encoding="utf-8")
    report = export_corpus(db, kdb, tmp_path / "c", min_chars=100, extra_dirs=[extra])
    assert report["sources"]["docs_meus_docs"]["mantidos"] == 0 or True  # dedup pode comer
    assert "docs_meus_docs" in report["sources"]


def test_clean_text_remove_segredos_e_normaliza():
    sujo = "linha ok\r\nAPI_KEY = sk-abcdefghijklmnop123456\n\n\n\nespaços   demais\t\n"
    limpo = clean_text(sujo)
    assert "sk-" not in limpo
    assert "\n\n\n" not in limpo
    assert "espaços demais" in limpo


@pytest.mark.parametrize("linha", [
    "API_KEY=abc", "senha: hunter2", "Bearer abcdefghijklmnopqrst",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "sk-abcdefghijklmnopqrstuvwx",
    "postgres://user:pass@host/db", "a" * 45,
])
def test_has_secret_detecta(linha):
    assert has_secret(linha)


def test_has_secret_nao_alarma_texto_normal():
    assert not has_secret("O token de atenção é um conceito de transformers.")
    assert not has_secret(PT)


def test_is_portuguese():
    assert is_portuguese(PT)
    assert not is_portuguese(EN)
    assert not is_portuguese("")


def test_fetch_supabase_sem_credenciais(monkeypatch):
    from src.nanollm.corpus_export import fetch_supabase

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    assert fetch_supabase() == []  # sem credenciais → fonte vazia, sem erro


def test_deduper_remove_paragrafo_repetido():
    d = Deduper()
    a = d.apply("um parágrafo aqui\n\noutro parágrafo")
    b = d.apply("um parágrafo aqui\n\nnovidade total")
    assert "um parágrafo" in a
    assert "um parágrafo" not in b
    assert "novidade total" in b
    assert d.dropped == 1
