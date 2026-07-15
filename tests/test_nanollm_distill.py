"""Flywheel de destilação (M25): o professor (Qwen) rotula, o Nano aprende.

Núcleo determinístico — o professor é um fake, sem LLM nem rede.
"""
import json

import numpy as np
import pytest

from src.nanollm.distill import (
    _parse_qa,
    distill_answers,
    distill_titles,
    generate_distill_pairs,
    make_llm_teacher,
    run_distillation,
    run_knowledge_distillation,
    run_reaction_distillation,
    source_knowledge_grounded_pairs,
    source_reaction_pairs,
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
    """Banco falso: o que o sourcing usa (first_user_messages + histórico)."""
    def __init__(self, msgs, summaries=None, reaction_pairs=None):
        self._msgs = msgs
        self._summaries = summaries or []
        self._reaction_pairs = reaction_pairs or []

    def first_user_messages(self, limit=300, min_len=8):
        return [m for m in self._msgs if len(m.strip()) >= min_len][:limit]

    def get_learning_history(self, limit=30):
        return [{"topic": f"t{i}", "summary": s} for i, s in enumerate(self._summaries)][:limit]

    def positive_reaction_pairs(self, limit=300, min_len=8):
        return self._reaction_pairs[:limit]


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


def test_make_llm_teacher_cede_gpu_ao_usuario_antes_de_cada_rotulo(monkeypatch):
    """O flywheel roda em thread de fundo e rotula várias entradas — sem ceder o
    GpuGate, ele seguraria o lock do motor e faria o chat do usuário esperar atrás
    do treino noturno (mesma classe de bug já corrigida no learner)."""
    fake = _FakeProvider()
    monkeypatch.setattr("src.providers.get_provider", lambda: fake)

    calls = {"n": 0}

    class _FakeGate:
        def wait_for_idle_sync(self, *a, **k):
            calls["n"] += 1

    import src.runtime as rt
    monkeypatch.setattr(rt, "gpu_gate", _FakeGate())
    teacher = make_llm_teacher(model="apolo", max_tokens=32)
    teacher("qual título?")
    teacher("outro prompt")
    assert calls["n"] == 2                  # cedeu ANTES de cada chamada ao professor


def test_make_llm_teacher_segue_funcionando_sem_gate(monkeypatch):
    """Sem gpu_gate configurado (ex.: testes/CLI), o teacher não pode quebrar."""
    fake = _FakeProvider()
    monkeypatch.setattr("src.providers.get_provider", lambda: fake)
    import src.runtime as rt
    monkeypatch.setattr(rt, "gpu_gate", None)
    teacher = make_llm_teacher(model="apolo", max_tokens=32)
    assert teacher("qual título?").startswith("Título")


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


# ── M28: destilação de resposta curta ──
def test_distill_answers_aceita_curta_e_rejeita_lixo():
    # professor bom: resposta curta e factual → aceita
    good = distill_answers(["O que é uma LLM?"],
                           lambda p: "É um modelo de linguagem treinado em texto.")
    assert good and good[0][0] == "O que é uma LLM?"
    # professor ruim: despeja código/markdown longo → barrado por _valid_answer
    bad = distill_answers(["Como faço um loop?"],
                          lambda p: "```python\n" + ("x = 1\n" * 10) + "```")
    assert bad == []


# ── M28: Q&A ancorado no banco de conhecimento dos 7 agentes ──
def test_parse_qa_extrai_pergunta_e_resposta():
    q, a = _parse_qa("P: O que é RAG?\nR: Recuperação aumentada por geração.")
    assert q == "O que é RAG?" and a == "Recuperação aumentada por geração."
    q2, a2 = _parse_qa("Pergunta: X?\nResposta: Y.")   # forma por extenso
    assert q2 == "X?" and a2 == "Y."
    assert _parse_qa("sem formato") == (None, None)


def test_source_knowledge_grounded_pairs():
    db = _FakeDB([], summaries=[
        "Kubernetes orquestra contêineres, escalando e reiniciando serviços automaticamente em um cluster.",
        "curto",   # < 40 chars → ignorado (não ancora)
    ])
    # professor ancorado devolve P:/R: a partir da síntese
    def teacher(prompt):
        return "P: O que o Kubernetes faz?\nR: Orquestra contêineres num cluster."
    pairs = source_knowledge_grounded_pairs(db, teacher)
    assert len(pairs) == 1
    assert pairs[0][0].startswith("O que o Kubernetes")


def test_run_knowledge_distillation(tokenizer, tmp_path):
    db = _FakeDB([], summaries=[
        "FastAPI é um framework web assíncrono em Python, rápido e com tipagem.",
        "Postgres é um banco relacional robusto com suporte a JSON e transações ACID.",
        "Redis é um armazenamento em memória usado como cache e fila de mensagens.",
    ])
    n = [0]

    def teacher(prompt):
        n[0] += 1                                  # perguntas distintas por síntese
        return f"P: Para que serve a tecnologia {n[0]}?\nR: Serve para construir sistemas."
    meta = run_knowledge_distillation(db, tokenizer, tmp_path / "kd",
                                      teacher_fn=teacher, val_fraction=0.34)
    assert meta["task"] == "answer_distill_grounded" and meta["pairs"] == 3
    assert "knowledge grounded" in meta["source"]
    assert (tmp_path / "kd" / "pairs.jsonl").exists()


def test_run_knowledge_distillation_sem_sinteses_falha(tokenizer, tmp_path):
    with pytest.raises(ValueError):
        run_knowledge_distillation(_FakeDB([], summaries=[]), tokenizer, tmp_path / "x",
                                   teacher_fn=lambda p: "P: a?\nR: b.")


# ── reações (👍) viram par de treino direto, sem professor (2026-07-15) ──
def test_source_reaction_pairs_valida_e_repassa():
    db = _FakeDB([], reaction_pairs=[
        ("O que é uma LLM?", "É um modelo de linguagem treinado em texto."),
        ("pergunta lixo", "```codigo\nque nao deveria contar\n```"),  # inválida
    ])
    pairs = source_reaction_pairs(db)
    assert pairs == [("O que é uma LLM?", "É um modelo de linguagem treinado em texto.")]


def test_run_reaction_distillation(tokenizer, tmp_path):
    db = _FakeDB([], reaction_pairs=[
        ("O que é RAG?", "É busca aumentando o contexto antes de gerar a resposta."),
        ("O que é Python?", "É uma linguagem de programação de propósito geral."),
    ])
    meta = run_reaction_distillation(db, tokenizer, tmp_path / "rd", val_fraction=0.34)
    assert meta["task"] == "answer_distill_reactions" and meta["pairs"] == 2
    assert "reações do Leo" in meta["source"]
    assert (tmp_path / "rd" / "pairs.jsonl").exists()


def test_run_reaction_distillation_sem_pares_falha(tokenizer, tmp_path):
    with pytest.raises(ValueError):
        run_reaction_distillation(_FakeDB([], reaction_pairs=[]), tokenizer, tmp_path / "x")
