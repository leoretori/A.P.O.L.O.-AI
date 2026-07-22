"""Flywheel noturno (M25.3): destila → treina candidato → promove só se melhorar.

Núcleo DETERMINÍSTICO — treino/avaliação/professor são fakes injetados. Nenhum
NumPy pesado, nenhuma LLM: os testes exercitam TODA a decisão de promoção.
"""
import json
from pathlib import Path

import pytest

from src.nanollm.flywheel import (
    read_flywheel_log,
    revert_promotion,
    run_nightly_flywheel,
)
from src.nanollm.tokenizer import ByteBPETokenizer

PT = "Como criar a própria LLM soberana em Python do zero. Título curto de conversa. "


class _FakeDB:
    def __init__(self, n, reaction_pairs=None):
        self._msgs = [f"Pergunta numero {i} sobre um tema tecnico do projeto" for i in range(n)]
        self._reaction_pairs = reaction_pairs or []

    def first_user_messages(self, limit=300, min_len=8):
        return self._msgs[:limit]

    def positive_reaction_pairs(self, limit=300, min_len=8):
        return self._reaction_pairs[:limit]


def _good_teacher(prompt):
    return "Titulo Curto Bom"           # PT, curto → passa no _valid_title


@pytest.fixture()
def live_ckpt(tmp_path):
    """Checkpoint 'vivo' com tokenizer + um peso fake (para o backup ter o que copiar)."""
    live = tmp_path / "live"
    live.mkdir()
    tok = ByteBPETokenizer()
    tok.train(PT * 30, vocab_size=400)
    tok.save(live / "tokenizer.json")
    (live / "model_best.npz").write_bytes(b"MODELO_TITULAR")
    (live / "state.json").write_text('{"step": 5000}', encoding="utf-8")
    return live


def _fake_train_factory():
    """train_fn fake: escreve os pesos do candidato e registra que rodou."""
    calls = {}

    def train_fn(dataset, init_from, out_dir, *, steps, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "model_best.npz").write_bytes(b"MODELO_CANDIDATO")
        (out_dir / "state.json").write_text('{"step": %d}' % steps, encoding="utf-8")
        calls["init_from"] = str(init_from)
        calls["steps"] = steps
        return {"best_val": 0.0}

    return train_fn, calls


def _eval_fn(cand_val, base_val):
    def ev(ckpt_dir, data_dir):
        return {"val": cand_val if "candidate" in str(ckpt_dir) else base_val}
    return ev


# Os testes de DECISÃO usam poucos pares fake → val destilado minúsculo. O
# portão de volume (`min_val_tokens`, E1b) é testado à parte, em
# `test_pula_com_val_curto_demais`; aqui ele sai da frente de propósito.
NO_VOLUME_GATE = 0


def test_promove_quando_candidato_melhora(live_ckpt, tmp_path):
    train_fn, calls = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        eval_fn=_eval_fn(cand_val=3.0, base_val=5.0), steps=120,
        min_val_tokens=NO_VOLUME_GATE)
    assert res["status"] == "promoted"
    assert res["gain"] == 2.0
    assert calls["init_from"] == str(live_ckpt)      # warm-start do titular
    # o peso vivo agora é o do candidato (promoção efetiva)
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_CANDIDATO"


def test_rejeita_quando_candidato_nao_melhora(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        eval_fn=_eval_fn(cand_val=5.0, base_val=4.9), steps=120,
        min_val_tokens=NO_VOLUME_GATE)
    assert res["status"] == "rejected"
    # titular INTACTO — nada foi promovido
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_TITULAR"


def test_pula_com_poucos_pares(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(3), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        eval_fn=_eval_fn(1, 1), min_pairs=12)
    assert res["status"] == "skipped" and "poucos pares" in res["reason"]


def test_pula_com_val_curto_demais(live_ckpt, tmp_path):
    """E1b: pares suficientes, mas val destilado minúsculo → pula ANTES de
    treinar (não queima 400 passos de CPU para medir ppl em ~60 tokens)."""
    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher,
        train_fn=lambda *a, **k: pytest.fail("não devia treinar com val curto"),
        eval_fn=_eval_fn(1, 1), min_pairs=12, min_val_tokens=10_000)
    assert res["status"] == "skipped" and "não seria confiável" in res["reason"]
    assert res["val_tokens"] < 10_000


def test_pula_sem_tokenizer(tmp_path):
    live = tmp_path / "vazio"
    live.mkdir()
    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        eval_fn=_eval_fn(1, 1))
    assert res["status"] == "skipped" and "tokenizer" in res["reason"]


def test_backup_e_revert(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(20), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        eval_fn=_eval_fn(cand_val=2.0, base_val=8.0), steps=120,
        min_val_tokens=NO_VOLUME_GATE)
    assert res["status"] == "promoted"
    # backup guardou o titular anterior → revert restaura
    revert_promotion(live_ckpt, res["backup_dir"])
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_TITULAR"


# ── source="reactions" (M5.3): os 👍 do Leo já são o rótulo ─────────────
_REACTION_PAIRS = [
    (f"Pergunta real numero {i} bem longa o suficiente", f"Resposta aprovada numero {i} bem longa")
    for i in range(20)
]


def test_reactions_nao_chama_o_professor(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()

    def _teacher_nunca_chamado(prompt):
        pytest.fail("source=reactions não deveria chamar o professor")

    res = run_nightly_flywheel(
        _FakeDB(0, reaction_pairs=_REACTION_PAIRS), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        teacher_fn=_teacher_nunca_chamado, train_fn=train_fn,
        eval_fn=_eval_fn(cand_val=3.0, base_val=5.0), steps=120,
        min_val_tokens=NO_VOLUME_GATE)
    assert res["status"] == "promoted"
    assert res["source"] == "reactions"


def test_reactions_pula_com_poucos_pares(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(0, reaction_pairs=_REACTION_PAIRS[:3]), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        eval_fn=_eval_fn(1, 1), min_pairs=12)
    assert res["status"] == "skipped" and "poucos pares" in res["reason"]


def test_reactions_sem_pares_pula_sem_treinar(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(0, reaction_pairs=[]), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        eval_fn=_eval_fn(1, 1))
    assert res["status"] == "skipped"


def test_title_e_reactions_sao_datasets_isolados(live_ckpt, tmp_path):
    """Mesma noite, DUAS fontes — cada uma no seu diretório de trabalho,
    nunca misturadas (lição do M14.2)."""
    train_fn, _ = _fake_train_factory()
    db = _FakeDB(20, reaction_pairs=_REACTION_PAIRS)
    r1 = run_nightly_flywheel(db, live_ckpt=live_ckpt, work_root=tmp_path / "fw",
                              source="title", teacher_fn=_good_teacher, train_fn=train_fn,
                              eval_fn=_eval_fn(cand_val=3.0, base_val=5.0), steps=120,
                              min_val_tokens=NO_VOLUME_GATE)
    r2 = run_nightly_flywheel(db, live_ckpt=live_ckpt, work_root=tmp_path / "fw",
                              source="reactions", train_fn=train_fn,
                              eval_fn=_eval_fn(cand_val=3.0, base_val=5.0), steps=120,
                              min_val_tokens=NO_VOLUME_GATE)
    assert r1["source"] == "title" and r2["source"] == "reactions"
    assert Path(r1["candidate_dir"]).parent != Path(r2["candidate_dir"]).parent


def test_ledger_registra_cada_noite(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    work = tmp_path / "fw"
    run_nightly_flywheel(_FakeDB(20), live_ckpt=live_ckpt, work_root=work,
                         teacher_fn=_good_teacher, train_fn=train_fn,
                         eval_fn=_eval_fn(3.0, 5.0), steps=120, min_val_tokens=NO_VOLUME_GATE)
    log = read_flywheel_log(work)
    assert len(log) == 1 and log[0]["status"] == "promoted"
    # o ledger é JSONL append-only
    raw = (work / "flywheel_log.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(raw)["status"] == "promoted"
