"""Dataset de tarefa para fine-tune (src/nanollm/taskdata) — Épico 4.1."""

import json
import sqlite3

import numpy as np
import pytest

from src.nanollm.taskdata import (
    TITLE_TEMPLATE,
    _binary_question,
    _valid_title,
    build_binary_dataset,
    build_sector_dataset,
    build_task_dataset,
    collect_binary_pairs,
    collect_sector_pairs,
    collect_title_pairs,
)
from src.nanollm.tokenizer import ByteBPETokenizer

PT = ("O aprendizado de máquina é uma área da computação que estuda como os "
      "sistemas aprendem com os dados sem serem programados de forma explícita. ")


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "apolo.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE learned_topics (id INTEGER PRIMARY KEY, topic TEXT, "
                "url TEXT, summary TEXT, category TEXT, studied_at TEXT)")
    con.execute("CREATE TABLE session_meta (session_id TEXT PRIMARY KEY, title TEXT, "
                "created_at TEXT)")
    con.execute("CREATE TABLE session_messages (id INTEGER PRIMARY KEY, session_id TEXT, "
                "role TEXT, content TEXT, timestamp TEXT)")
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("Aprendizado de Máquina", PT * 2, "web_search"))
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("Redes Neurais", "As redes neurais são modelos que aprendem com dados. " * 2,
                 "official_doc"))
    # título ruim (longo demais) → descartado
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("um título muito muito muito muito muito muito longo demais", PT, "web"))
    # summary curto → descartado
    con.execute("INSERT INTO learned_topics (topic, summary, category) VALUES (?,?,?)",
                ("Curto", "oi", "web"))
    con.execute("INSERT INTO session_meta VALUES (?,?,?)", ("s1", "Como criar uma LLM?", ""))
    con.execute("INSERT INTO session_messages VALUES (1,'s1','user','Como criar a própria LLM',' ')")
    con.commit()
    con.close()
    return p


@pytest.fixture()
def tokenizer(tmp_path):
    tok = ByteBPETokenizer()
    tok.train((PT + "Redes neurais aprendem. Como criar uma LLM própria. ") * 20,
              vocab_size=400)
    path = tmp_path / "tok.json"
    tok.save(path)
    return path


def test_valid_title():
    assert _valid_title("Aprendizado de Máquina")
    assert _valid_title("Redes Neurais")
    assert not _valid_title("ab")
    assert not _valid_title("x " * 20)
    assert not _valid_title("veja https://x.com")
    assert not _valid_title("linha\ncom quebra")
    # inglês barrado (os topics de web_search são queries em inglês)
    assert not _valid_title("privacy by design principles")
    assert not _valid_title("compound interest fundamentals")
    assert not _valid_title("how to build an API")


def test_collect_pairs(db):
    pairs = collect_title_pairs(db)
    titles = [t for _, t in pairs]
    assert "Aprendizado de Máquina" in titles
    assert "Redes Neurais" in titles
    assert "Como criar uma LLM?" in titles       # veio da conversa real
    assert not any(len(t) > 60 for t in titles)   # o título longo foi barrado
    assert "Curto" not in titles                  # summary curto barrado


def test_build_dataset(db, tokenizer, tmp_path):
    out = tmp_path / "tasks"
    meta = build_task_dataset(db, tokenizer, out, val_fraction=0.2, verbose=False)

    assert meta["task"] == "title"
    assert meta["pairs"] >= 3
    assert meta["tokens"] == meta["train_tokens"] + meta["val_tokens"]
    assert meta["val_tokens"] > 0

    train = np.load(out / "train.npy")
    tok = ByteBPETokenizer.load(tokenizer)
    assert train.dtype == np.uint16
    assert meta["vocab_size"] == tok.vocab_size
    assert int(train.max()) < tok.vocab_size

    # o template de treino tem que casar EXATAMENTE o prompt de inferência
    from src.nanollm.tasks import title_prompt
    rendered = TITLE_TEMPLATE.format(context="X", title="Y")
    assert title_prompt("X").rstrip() == rendered.rsplit("Y", 1)[0].rstrip()

    pairs_file = (out / "pairs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(pairs_file[0]).keys() == {"context", "title"}


def test_build_dataset_deterministico(db, tokenizer, tmp_path):
    m1 = build_task_dataset(db, tokenizer, tmp_path / "a", seed=1, verbose=False)
    m2 = build_task_dataset(db, tokenizer, tmp_path / "b", seed=1, verbose=False)
    assert m1 == m2
    assert np.array_equal(np.load(tmp_path / "a" / "train.npy"),
                          np.load(tmp_path / "b" / "train.npy"))


@pytest.fixture()
def sector_db(tmp_path):
    """Banco com tópicos suficientes p/ 2 setores passarem o min_examples=3."""
    p = tmp_path / "sec.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE learned_topics (id INTEGER PRIMARY KEY, topic TEXT, "
                "url TEXT, summary TEXT, category TEXT, studied_at TEXT)")
    for i in range(5):
        con.execute("INSERT INTO learned_topics (topic, summary) VALUES (?,?)",
                    (f"FastAPI endpoint REST {i}",
                     f"Como criar uma API REST com FastAPI e pydantic exemplo {i}. " * 2))
    for i in range(5):
        con.execute("INSERT INTO learned_topics (topic, summary) VALUES (?,?)",
                    (f"React componente {i}",
                     f"Como criar um componente React com hooks e css exemplo {i}. " * 2))
    con.execute("INSERT INTO learned_topics (topic, summary) VALUES (?,?)",
                ("tópico raro solitário", "conteúdo de um setor que aparece só uma vez aqui. " * 2))
    con.commit()
    con.close()
    return p


def test_collect_sector_pairs(sector_db):
    pairs, labels = collect_sector_pairs(sector_db, min_examples=3)
    assert "backend_apis" in labels and "frontend_web" in labels
    assert len(pairs) >= 10
    # o setor raro (1 exemplo) foi descartado, não virou 'outros' inflado
    assert all(s in labels for _, s in pairs)
    assert len({s for _, s in pairs}) == len(labels)


def test_build_sector_dataset(sector_db, tokenizer, tmp_path):
    out = tmp_path / "sectors"
    meta = build_sector_dataset(sector_db, tokenizer, out, val_fraction=0.2,
                                min_examples=3, verbose=False)
    assert meta["task"] == "sector"
    assert set(meta["labels"]) >= {"backend_apis", "frontend_web"}
    assert sum(meta["label_counts"].values()) == meta["pairs"]
    assert meta["tokens"] == meta["train_tokens"] + meta["val_tokens"]

    # o template de treino casa o prompt de inferência
    from src.nanollm.tasks import sector_prompt
    from src.nanollm.taskdata import SECTOR_TEMPLATE
    rendered = SECTOR_TEMPLATE.format(context="X", label="Y")
    assert sector_prompt("X").rstrip() == rendered.rsplit("Y", 1)[0].rstrip()


# ── Gate binário (M27+): mesma fonte, framing sim/não ─────────────
def test_binary_question_tira_o_emoji():
    assert _binary_question("backend_apis") == "É Backend & APIs?"
    assert _binary_question("nao_existe") == "É nao existe?"


def test_collect_binary_pairs_balanceia_classes(sector_db):
    pairs = collect_binary_pairs(sector_db, "backend_apis", min_per_class=3)
    answers = [a for _, a in pairs]
    assert answers.count("sim") == answers.count("não")   # balanceado
    assert set(answers) == {"sim", "não"}
    # todo "sim" veio mesmo de um tópico de backend (não é rótulo furado)
    sims = {c for c, a in pairs if a == "sim"}
    assert all("fastapi" in c.lower() or "api" in c.lower() for c in sims)


def test_collect_binary_pairs_poucos_pares_levanta_erro(sector_db):
    with pytest.raises(ValueError, match="poucos pares"):
        collect_binary_pairs(sector_db, "backend_apis", min_per_class=100)


def test_collect_binary_pairs_deterministico(sector_db):
    p1 = collect_binary_pairs(sector_db, "backend_apis", min_per_class=3, seed=7)
    p2 = collect_binary_pairs(sector_db, "backend_apis", min_per_class=3, seed=7)
    assert p1 == p2


def test_build_binary_dataset(sector_db, tokenizer, tmp_path):
    out = tmp_path / "binary"
    meta = build_binary_dataset(sector_db, tokenizer, out, "backend_apis",
                                val_fraction=0.2, min_per_class=3, verbose=False)
    assert meta["task"] == "binary:backend_apis"
    assert meta["question"] == "É Backend & APIs?"
    assert meta["label_counts"]["sim"] == meta["label_counts"]["não"]
    assert meta["tokens"] == meta["train_tokens"] + meta["val_tokens"]

    # o template de treino casa o prompt de inferência
    from src.nanollm.taskdata import BINARY_TEMPLATE
    from src.nanollm.tasks import binary_prompt
    rendered = BINARY_TEMPLATE.format(context="X", question="É Y?", answer="sim")
    assert binary_prompt("X", "É Y?").rstrip() == rendered.rsplit("sim", 1)[0].rstrip()

    pairs_file = (out / "pairs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(pairs_file[0]).keys() == {"context", "question", "answer"}


def test_build_binary_dataset_poucos_pares_nao_grava_nada(sector_db, tokenizer, tmp_path):
    out = tmp_path / "binary_vazio"
    with pytest.raises(ValueError):
        build_binary_dataset(sector_db, tokenizer, out, "backend_apis",
                             min_per_class=100, verbose=False)
    assert not (out / "meta.json").exists()


def test_build_sem_pares(tmp_path, tokenizer):
    empty = tmp_path / "empty.db"
    con = sqlite3.connect(empty)
    con.execute("CREATE TABLE learned_topics (id INTEGER PRIMARY KEY, topic TEXT, "
                "url TEXT, summary TEXT, category TEXT, studied_at TEXT)")
    con.execute("CREATE TABLE session_meta (session_id TEXT PRIMARY KEY, title TEXT, "
                "created_at TEXT)")
    con.execute("CREATE TABLE session_messages (id INTEGER PRIMARY KEY, session_id TEXT, "
                "role TEXT, content TEXT, timestamp TEXT)")
    con.commit()
    con.close()
    with pytest.raises(ValueError):
        build_task_dataset(empty, tokenizer, tmp_path / "out", verbose=False)
