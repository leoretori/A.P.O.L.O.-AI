"""Flywheel pelo CAMINHO REAL — sem `eval_fn` fake (E1/E1b/E12/E28).

A suíte antiga injetava `eval_fn` que devolvia `{"val": <número>}`, então o
`_default_eval` de verdade — que devolvia o relatório inteiro, com `["val"]`
sendo um DICT — nunca era exercitado: o ciclo noturno treinava 400 passos e só
então crashava em `float(dict)`. Aqui o medidor é o REAL, sobre checkpoints de
verdade (modelo NumPy minúsculo + tokenizer treinado), sem nenhuma LLM.
"""
import json

import numpy as np
import pytest

from src.nanollm.eval import evaluate, perplexity
from src.nanollm.flywheel import _default_eval, run_nightly_flywheel
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.tokenizer import ByteBPETokenizer

PT = ("Como criar a propria LLM soberana em Python do zero. Titulo curto de "
      "conversa sobre engenharia de software e aprendizado de maquina. ")


class _FakeDB:
    def __init__(self, n):
        self._msgs = [f"Pergunta numero {i} sobre um tema tecnico do projeto" for i in range(n)]

    def first_user_messages(self, limit=300, min_len=8):
        return self._msgs[:limit]

    def positive_reaction_pairs(self, limit=300, min_len=8):
        return []


def _good_teacher(prompt):
    return "Titulo Curto Bom"


def _real_ckpt(path, tok, *, seed=1):
    """Checkpoint de verdade: pesos NumPy carregáveis + tokenizer + state."""
    path.mkdir(parents=True, exist_ok=True)
    model = GPT(GPTConfig(vocab_size=tok.vocab_size, block_size=16, n_layer=1,
                          n_head=2, n_embd=32, seed=seed))
    model.save(path / "model_best.npz")
    tok.save(path / "tokenizer.json")
    (path / "state.json").write_text(json.dumps({"step": 100}), encoding="utf-8")
    return path


@pytest.fixture()
def tok():
    t = ByteBPETokenizer()
    t.train(PT * 30, vocab_size=400)
    return t


def test_default_eval_devolve_numero_nao_dict(tmp_path, tok):
    """E1: o contrato do portão é escalar — `float(ev(...)["val"])` tem que
    funcionar. Antes, `["val"]` era `{"nll":…, "ppl":…}` → TypeError."""
    ckpt = _real_ckpt(tmp_path / "ckpt", tok)
    data = tmp_path / "data"
    data.mkdir()
    rng = np.random.default_rng(0)
    np.save(data / "val.npy", rng.integers(0, tok.vocab_size, 600).astype(np.uint16))

    out = _default_eval(ckpt, data)
    assert float(out["val"]) > 0            # é o `float()` que crashava
    assert out["report"]["val"]["ppl"] == out["val"]


def test_default_eval_nao_sobrescreve_relatorio_do_ckpt(tmp_path, tok):
    """E12: medir o titular num dataset qualquer não pode mexer no
    `eval_report.json` que o /api/nano/status mostra."""
    ckpt = _real_ckpt(tmp_path / "ckpt", tok)
    data = tmp_path / "data"
    data.mkdir()
    rng = np.random.default_rng(0)
    np.save(data / "val.npy", rng.integers(0, tok.vocab_size, 600).astype(np.uint16))

    evaluate(ckpt, data, probes=False)                       # relatório oficial
    oficial = (ckpt / "eval_report.json").read_text(encoding="utf-8")
    linhas_antes = len((ckpt / "evals.jsonl").read_text(encoding="utf-8").splitlines())

    _default_eval(ckpt, data)                                # medição do flywheel
    assert (ckpt / "eval_report.json").read_text(encoding="utf-8") == oficial
    assert len((ckpt / "evals.jsonl").read_text(encoding="utf-8").splitlines()) == linhas_antes


def test_perplexity_aceita_val_curto_com_janela_reduzida(tok):
    """E1b: val menor que uma janela cheia mede com janela menor em vez de
    levantar ValueError e matar o ciclo."""
    model = GPT(GPTConfig(vocab_size=tok.vocab_size, block_size=256, n_layer=1,
                          n_head=2, n_embd=32, seed=1))
    curto = np.random.default_rng(0).integers(0, tok.vocab_size, 80).astype(np.uint16)
    r = perplexity(model, curto)
    assert r["ppl"] > 0 and r["windows"] >= 1
    assert r["block"] == 78 < model.config.block_size   # janela encolheu, e o diz


def test_perplexity_val_impossivel_ainda_falha(tok):
    model = GPT(GPTConfig(vocab_size=tok.vocab_size, block_size=16, n_layer=1,
                          n_head=2, n_embd=32, seed=1))
    with pytest.raises(ValueError):
        perplexity(model, np.zeros(2, dtype=np.uint16))


def test_ciclo_completo_com_medidor_real(tmp_path, tok):
    """O ciclo inteiro (destila → treina → MEDE → decide) sem NENHUM fake de
    medição: portão de tarefa real (gera título com o modelo e passa pelo
    `title_ok`/`title_relevant`) + ppl real. É a regressão do E1 e do E6 de
    ponta a ponta. O treino continua fake (custo), mas escreve um checkpoint
    REAL, que os medidores reais carregam."""
    live = _real_ckpt(tmp_path / "live", tok, seed=1)

    def train_fn(dataset, init_from, out_dir, *, steps, **kw):
        _real_ckpt(out_dir, tok, seed=2)     # candidato = outro modelo de verdade
        return {"best_val": 0.0}

    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn, steps=10,
        min_pairs=5, min_val_tokens=0, min_gate_items=5,
        title_messages_path=tmp_path / "held_out.json",
        questions_path=tmp_path / "perguntas.json")

    assert res["status"] in ("promoted", "rejected")    # decidiu — não crashou
    assert isinstance(res["candidate_val"], float)      # ppl real (informativa)
    assert isinstance(res["incumbent_val"], float)
    assert res["candidate_accept"] is not None          # tarefa real (decisiva)
    assert res["teste_pareado"]["pareadas"] == 5
