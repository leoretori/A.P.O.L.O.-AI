"""Flywheel noturno (M25.3): destila → treina candidato → promove só se melhorar.

Núcleo DETERMINÍSTICO — treino/portão/professor são fakes injetados. Nenhum
NumPy pesado, nenhuma LLM: os testes exercitam TODA a decisão de promoção.

Desde o E6, o portão mede a TAREFA (taxa de aceitação do título / blind-eval),
não a perplexidade, e exige delta pareado significativo — por isso o fake de
portão devolve o veredito POR ITEM, não só a média.
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
        calls["dataset"] = str(dataset)
        return {"best_val": 0.0}

    return train_fn, calls


def _gate_fn(cand_ok, base_ok):
    """Portão fake: `cand_ok`/`base_ok` são os ÍNDICES em que cada checkpoint
    acertou a tarefa. O que decide é o pareamento item a item (E6)."""
    def gate(ckpt_dir, items):
        acertos = set(cand_ok if "candidate" in str(ckpt_dir) else base_ok)
        rounds = [{"i": i, "ok": i in acertos} for i in range(len(items))]
        n_ok = sum(1 for r in rounds if r["ok"])
        return {"status": "ok", "n": len(items), "aceitos": n_ok,
                "accept_rate": round(100 * n_ok / len(items), 1) if items else 0.0,
                "rounds": rounds}
    return gate


def _eval_fn(cand_val, base_val):
    """Medidor de ppl (hoje só informativo — não decide nada)."""
    def ev(ckpt_dir, data_dir):
        return {"val": cand_val if "candidate" in str(ckpt_dir) else base_val}
    return ev


def _paths(tmp_path):
    """Conjuntos congelados sempre em tmp — nunca no data/ do repositório."""
    return {"title_messages_path": tmp_path / "held_out.json",
            "questions_path": tmp_path / "perguntas.json"}


def test_promove_quando_candidato_melhora(live_ckpt, tmp_path):
    train_fn, calls = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(12), base_ok=[]),
        eval_fn=_eval_fn(3.0, 5.0), steps=120, min_gate_items=15,
        min_val_tokens=0, **_paths(tmp_path))
    assert res["status"] == "promoted"
    assert res["teste_pareado"]["significativo"] is True
    assert calls["init_from"] == str(live_ckpt)      # warm-start do titular
    # o peso vivo agora é o do candidato (promoção efetiva)
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_CANDIDATO"


def test_rejeita_quando_candidato_nao_melhora(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(2), base_ok=range(10)),
        steps=120, min_gate_items=15, min_val_tokens=0, **_paths(tmp_path))
    assert res["status"] == "rejected"
    # titular INTACTO — nada foi promovido
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_TITULAR"


def test_ppl_melhor_nao_promove_sozinha(live_ckpt, tmp_path):
    """E6: o candidato treina na MESMA distribuição do val destilado, então
    quase sempre 'ganha' no ppl. Ppl melhor + tarefa igual = nada muda."""
    train_fn, _ = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(5), base_ok=range(5)),   # tarefa idêntica
        eval_fn=_eval_fn(cand_val=1.0, base_val=99.0),          # ppl MUITO melhor
        steps=120, min_gate_items=15, min_val_tokens=0, **_paths(tmp_path))
    assert res["status"] == "rejected"
    assert res["candidate_val"] < res["incumbent_val"]   # a ppl segue no ledger…
    assert res["teste_pareado"]["discordantes"] == 0     # …mas quem decide é a tarefa
    assert (live_ckpt / "model_best.npz").read_bytes() == b"MODELO_TITULAR"


def test_held_out_fica_fora_do_treino(live_ckpt, tmp_path):
    """As mensagens do portão não podem virar dado de treino — senão o
    candidato é avaliado no que acabou de decorar."""
    train_fn, calls = _fake_train_factory()
    db = _FakeDB(40)
    paths = _paths(tmp_path)
    run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(12), base_ok=[]), steps=120,
        min_gate_items=15, min_val_tokens=0, **paths)

    held_out = set(json.loads(Path(paths["title_messages_path"]).read_text(encoding="utf-8")))
    assert len(held_out) == 15
    pares = [json.loads(ln) for ln in
             (Path(calls["dataset"]) / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    treinadas = {p["context"] for p in pares}
    assert not (treinadas & held_out)
    assert treinadas and treinadas <= set(db.first_user_messages())


def test_pula_com_poucos_pares(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        gate_fn=_gate_fn([], []), min_pairs=100, min_gate_items=15, **_paths(tmp_path))
    assert res["status"] == "skipped" and "poucos pares" in res["reason"]


def test_pula_sem_held_out_suficiente(live_ckpt, tmp_path):
    """E7/E6: sem conjunto de avaliação não há como decidir — pula ANTES de
    destilar e treinar."""
    res = run_nightly_flywheel(
        _FakeDB(3), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=lambda p: pytest.fail("não devia chamar o professor"),
        train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        gate_fn=_gate_fn([], []), min_gate_items=20, **_paths(tmp_path))
    assert res["status"] == "skipped" and "poucas mensagens" in res["reason"]


def test_pula_com_val_curto_demais(live_ckpt, tmp_path):
    """E1b: pares suficientes, mas val destilado minúsculo → pula ANTES de
    treinar (não queima 400 passos de CPU para medir ppl em ~60 tokens)."""
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher,
        train_fn=lambda *a, **k: pytest.fail("não devia treinar com val curto"),
        gate_fn=_gate_fn([], []), min_pairs=12, min_gate_items=15,
        min_val_tokens=10_000, **_paths(tmp_path))
    assert res["status"] == "skipped" and "não seria confiável" in res["reason"]
    assert res["val_tokens"] < 10_000


def test_pula_sem_tokenizer(tmp_path):
    live = tmp_path / "vazio"
    live.mkdir()
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        gate_fn=_gate_fn([], []), **_paths(tmp_path))
    assert res["status"] == "skipped" and "tokenizer" in res["reason"]


def test_backup_e_revert(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    res = run_nightly_flywheel(
        _FakeDB(40), live_ckpt=live_ckpt, work_root=tmp_path / "fw",
        teacher_fn=_good_teacher, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(12), base_ok=[]), steps=120,
        min_gate_items=15, min_val_tokens=0, **_paths(tmp_path))
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
        _FakeDB(40, reaction_pairs=_REACTION_PAIRS), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        teacher_fn=_teacher_nunca_chamado, train_fn=train_fn,
        gate_fn=_gate_fn(cand_ok=range(12), base_ok=[]), steps=120,
        min_gate_items=15, min_val_tokens=0, **_paths(tmp_path))
    assert res["status"] == "promoted"
    assert res["source"] == "reactions"


def test_reactions_pula_com_poucos_pares(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(40, reaction_pairs=_REACTION_PAIRS[:3]), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        gate_fn=_gate_fn([], []), min_pairs=12, min_gate_items=15, **_paths(tmp_path))
    assert res["status"] == "skipped" and "poucos pares" in res["reason"]


def test_reactions_sem_pares_pula_sem_treinar(live_ckpt, tmp_path):
    res = run_nightly_flywheel(
        _FakeDB(40, reaction_pairs=[]), live_ckpt=live_ckpt,
        work_root=tmp_path / "fw", source="reactions",
        train_fn=lambda *a, **k: pytest.fail("não devia treinar"),
        gate_fn=_gate_fn([], []), min_gate_items=15, **_paths(tmp_path))
    assert res["status"] == "skipped"


def test_title_e_reactions_sao_datasets_isolados(live_ckpt, tmp_path):
    """Mesma noite, DUAS fontes — cada uma no seu diretório de trabalho,
    nunca misturadas (lição do M14.2)."""
    train_fn, _ = _fake_train_factory()
    db = _FakeDB(40, reaction_pairs=_REACTION_PAIRS)
    gate = _gate_fn(cand_ok=range(12), base_ok=[])
    paths = _paths(tmp_path)
    r1 = run_nightly_flywheel(db, live_ckpt=live_ckpt, work_root=tmp_path / "fw",
                              source="title", teacher_fn=_good_teacher, train_fn=train_fn,
                              gate_fn=gate, steps=120, min_gate_items=15,
                              min_val_tokens=0, **paths)
    r2 = run_nightly_flywheel(db, live_ckpt=live_ckpt, work_root=tmp_path / "fw",
                              source="reactions", train_fn=train_fn,
                              gate_fn=gate, steps=120, min_gate_items=15,
                              min_val_tokens=0, **paths)
    assert r1["source"] == "title" and r2["source"] == "reactions"
    assert Path(r1["candidate_dir"]).parent != Path(r2["candidate_dir"]).parent


def test_ledger_registra_cada_noite(live_ckpt, tmp_path):
    train_fn, _ = _fake_train_factory()
    work = tmp_path / "fw"
    run_nightly_flywheel(_FakeDB(40), live_ckpt=live_ckpt, work_root=work,
                         teacher_fn=_good_teacher, train_fn=train_fn,
                         gate_fn=_gate_fn(cand_ok=range(12), base_ok=[]), steps=120,
                         min_gate_items=15, min_val_tokens=0, **_paths(tmp_path))
    log = read_flywheel_log(work)
    assert len(log) == 1 and log[0]["status"] == "promoted"
    # o ledger é JSONL append-only
    raw = (work / "flywheel_log.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(raw)["status"] == "promoted"
