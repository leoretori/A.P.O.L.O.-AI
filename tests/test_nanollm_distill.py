"""Flywheel de destilação (M25): o professor (Qwen) rotula, o Nano aprende.

Núcleo determinístico — o professor é um fake, sem LLM nem rede.
"""
import json

import numpy as np
import pytest

from src.nanollm.distill import (
    distill_titles,
    generate_distill_pairs,
    make_llm_teacher,
    run_distillation,
    source_title_inputs,
    write_distill_dataset,
)
from src.nanollm.tokenizer import ByteBPETokenizer

PT = "Como criar a própria LLM soberana em Python do zero sem depender de ninguém. "


@pytest.fixture()
def tokenizer(tmp_path):
    tok = ByteBPETokenizer()
    tok.train((PT + "Redes neurais aprendem com dados. Título curto de conversa. ") * 20,
              vocab_size=400)
    path = tmp_path / "tok.json"
    tok.save(path)
    return path


def test_generate_pairs_usa_o_professor_e_valida():
    # professor determinístico: devolve um "título" pela 1ª palavra da entrada
    def teacher(prompt):
        return "Título: " + prompt.split()[-1].strip("?.")  # simula ruído "Título:"
    inputs = ["Como criar uma LLM", "Explique asyncio"]
    pairs = generate_distill_pairs(inputs, teacher)
    assert len(pairs) == 2
    # o prefixo "Título:" e aspas foram limpos
    assert all(not lbl.startswith("Título:") for _, lbl in pairs)
    assert pairs[0][0] == "Como criar uma LLM"


def test_generate_pairs_pula_invalidos_e_dedup():
    def teacher(prompt):
        if "bolo" in prompt:
            return ""                     # professor sem resposta → pulado
        return "Assunto Técnico"
    inputs = ["pergunta sobre python", "receita de bolo",
              "pergunta sobre python  ", "x"]  # dup + curta demais
    pairs = generate_distill_pairs(inputs, teacher, validate=lambda s: len(s) > 3)
    assert len(pairs) == 1                # dedup + inválido + curta removidos


def test_generate_pairs_respeita_max():
    pairs = generate_distill_pairs(
        [f"pergunta numero {i} sobre um tema" for i in range(10)],
        lambda p: "Tema Qualquer", max_pairs=3)
    assert len(pairs) == 3


def test_distill_titles_rejeita_titulo_ruim():
    # professor "ruim": devolve título longo demais / em inglês → barrado por _valid_title
    def bad_teacher(prompt):
        return "this is a very long english title that should be rejected by the gate"
    assert distill_titles(["Como criar uma LLM?"], bad_teacher) == []
    # professor bom: título curto em PT → aceito
    good = distill_titles(["Como criar uma LLM?"], lambda p: "LLM do Zero em Python")
    assert good == [("Como criar uma LLM?", "LLM do Zero em Python")]


def test_professor_que_explode_nao_derruba():
    def flaky(prompt):
        if "quebra" in prompt:
            raise RuntimeError("timeout do professor")
        return "Título Válido"
    pairs = generate_distill_pairs(["pergunta boa", "isso quebra tudo"], flaky)
    assert len(pairs) == 1 and pairs[0][0] == "pergunta boa"


def test_write_distill_dataset(tokenizer, tmp_path):
    pairs = [("Como criar uma LLM?", "LLM do Zero"),
             ("Explique asyncio em python", "Asyncio em Python"),
             ("O que e um decorator", "Decorators em Python")]
    out = tmp_path / "distill"
    meta = write_distill_dataset(pairs, tokenizer, out, val_fraction=0.34)
    assert meta["task"] == "title_distill" and meta["pairs"] == 3
    assert meta["source"].startswith("distillation")
    assert meta["tokens"] == meta["train_tokens"] + meta["val_tokens"]
    assert meta["val_tokens"] > 0
    train = np.load(out / "train.npy")
    assert train.dtype == np.uint16
    # formato idêntico ao fine-tune (o train.py consome sem mudança)
    first = json.loads((out / "pairs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first.keys() == {"context", "title"}


def test_write_sem_pares_falha(tokenizer, tmp_path):
    with pytest.raises(ValueError):
        write_distill_dataset([], tokenizer, tmp_path / "x")


# ── M25.2: professor real + sourcing do banco (ainda determinístico) ──

class _FakeDB:
    """Banco falso: só o que o sourcing usa (first_user_messages)."""
    def __init__(self, msgs):
        self._msgs = msgs

    def first_user_messages(self, limit=300, min_len=8):
        return [m for m in self._msgs if len(m.strip()) >= min_len][:limit]


class _FakeProvider:
    def __init__(self):
        self.calls = []

    def list_models(self):
        return ["apolo"]

    def complete(self, model, messages, options=None):
        self.calls.append((model, messages, options))
        return "Título: Assunto Técnico"


def test_source_title_inputs_puxa_do_banco_e_filtra_curtas():
    db = _FakeDB(["Como criar uma LLM soberana?", "oi", "Explique asyncio no python"])
    got = source_title_inputs(db, min_len=8)
    assert "Como criar uma LLM soberana?" in got
    assert "oi" not in got                 # curta demais → filtrada pelo banco


def test_make_llm_teacher_chama_o_provider(monkeypatch):
    fake = _FakeProvider()
    monkeypatch.setattr("src.providers.get_provider", lambda: fake)
    teacher = make_llm_teacher(model="apolo", max_tokens=32)
    out = teacher("qual título?")
    assert out.startswith("Título")
    assert fake.calls[0][0] == "apolo"      # usou o modelo pedido
    assert fake.calls[0][1][0]["role"] == "user"


def test_run_distillation_ponta_a_ponta(tokenizer, tmp_path):
    db = _FakeDB(["Como criar uma LLM soberana?",
                  "Explique asyncio no python",
                  "O que e um decorator em python"])
    meta = run_distillation(db, tokenizer, tmp_path / "d",
                            teacher_fn=lambda prompt: "Assunto do Chat",
                            val_fraction=0.34)
    assert meta["inputs_seen"] == 3 and meta["pairs"] >= 1
    assert (tmp_path / "d" / "pairs.jsonl").exists()


def test_run_distillation_sem_entradas_falha(tokenizer, tmp_path):
    with pytest.raises(ValueError):
        run_distillation(_FakeDB([]), tokenizer, tmp_path / "x",
                         teacher_fn=lambda p: "Qualquer")
