"""Avaliação do portão binário no held-out val (src/nanollm/binary_eval, P1.3)."""

import json
import sqlite3

import pytest

from src.nanollm.binary_eval import evaluate_binary_gate, load_held_out
from src.nanollm.taskdata import build_binary_dataset
from src.nanollm.tokenizer import ByteBPETokenizer

PT = ("O aprendizado de máquina é uma área da computação que estuda como os "
      "sistemas aprendem com os dados sem serem programados de forma explícita. ")


@pytest.fixture()
def sector_db_binary(tmp_path):
    """Banco com tópicos suficientes p/ 2 setores passarem o min_per_class=3."""
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
    con.commit()
    con.close()
    return p


@pytest.fixture()
def tokenizer(tmp_path):
    tok = ByteBPETokenizer()
    tok.train((PT + "React hooks componente FastAPI API REST pydantic. ") * 20,
              vocab_size=300)
    path = tmp_path / "tok.json"
    tok.save(path)
    return path


class _FakeEngine:
    """Simula um portão: acerta o que fala de 'fastapi', recusa (None) o que
    tem 'talvez', erra o resto (react não é backend, mas o fake diz 'sim') —
    dá pra medir acurácia/recusa/decisão separadamente sem depender de um
    checkpoint treinado de verdade."""

    def available(self):
        return True

    def complete(self, prompt, max_tokens=4, temperature=0.2, top_k=5, seed=None):
        low = prompt.lower()
        if "talvez" in low:
            return {"text": "talvez", "tokens": 1, "ms": 1}
        if "fastapi" in low:
            return {"text": "sim", "tokens": 1, "ms": 1}
        return {"text": "sim", "tokens": 1, "ms": 1}  # erra o caso do react de propósito


def test_load_held_out_bate_com_o_split_do_dataset(tmp_path, sector_db_binary, tokenizer):
    out = tmp_path / "ds"
    meta = build_binary_dataset(sector_db_binary, tokenizer, out, "backend_apis",
                                val_fraction=0.2, min_per_class=3, verbose=False)
    question, held_out = load_held_out(out, val_fraction=0.2, seed=42)

    assert question == meta["question"]
    total_pairs = json.loads((out / "meta.json").read_text(encoding="utf-8"))["pairs"]
    assert len(held_out) == max(int(total_pairs * 0.2), 1)
    assert all(a in ("sim", "não") for _, a in held_out)


def test_load_held_out_e_deterministico(tmp_path, sector_db_binary, tokenizer):
    out = tmp_path / "ds"
    build_binary_dataset(sector_db_binary, tokenizer, out, "backend_apis",
                         val_fraction=0.2, min_per_class=3, verbose=False)
    q1, h1 = load_held_out(out, val_fraction=0.2, seed=42)
    q2, h2 = load_held_out(out, val_fraction=0.2, seed=42)
    assert h1 == h2


def test_evaluate_binary_gate_mede_acerto_recusa_decisao():
    engine = _FakeEngine()
    pairs = [
        ("uso fastapi pra construir uma api rest", "sim"),           # acerta
        ("estudei react com hooks", "não"),                          # erra (fake sempre diz sim)
        ("não tenho certeza do que isso é, talvez sim talvez não", "sim"),  # recusa
    ]
    r = evaluate_binary_gate(engine, "É Backend & APIs?", pairs)
    assert r["n"] == 3
    assert r["recusas"] == 1
    assert r["decididos"] == 2
    assert r["acertos"] == 1
    assert r["acuracia_geral"] == pytest.approx(1 / 3, abs=1e-4)
    assert r["acuracia_quando_decide"] == 0.5
    assert r["taxa_decisao"] == pytest.approx(2 / 3, abs=1e-4)


def test_evaluate_binary_gate_sem_pares():
    r = evaluate_binary_gate(_FakeEngine(), "É X?", [])
    assert r == {
        "n": 0, "acertos": 0, "recusas": 0, "decididos": 0,
        "acuracia_geral": 0.0, "acuracia_quando_decide": None, "taxa_decisao": 0.0,
    }
