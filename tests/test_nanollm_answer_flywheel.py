"""Flywheel de RESPOSTA (item 2 do PLANO_FLYWHEEL_AUTOMATICO.md): fine-tune
noturno com portão de BLIND-EVAL, não perplexidade — achado real de 3
experimentos manuais (PLANO_CORPUS_DIVERSO.md): ppl melhorou mas o blind-eval
mostrou piora nos três. Núcleo determinístico — treino/blind-eval são fakes."""
import json
from pathlib import Path

from src.nanollm.experiment_log import read_experiment_history
from src.nanollm.flywheel import run_answer_flywheel
from src.nanollm.tokenizer import ByteBPETokenizer

PT = "Como criar a própria LLM soberana em Python do zero, sem depender de terceiros. "


class _FakeDB:
    def __init__(self, n=80):
        self._msgs = [f"Pergunta numero {i} sobre um tema tecnico real" for i in range(n)]

    def first_user_messages(self, limit=300, min_len=8):
        return self._msgs[:limit]


def _write_dataset(path: Path, pairs: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "meta.json").write_text(json.dumps({"pairs": pairs}), encoding="utf-8")


def _live_ckpt(tmp_path) -> Path:
    live = tmp_path / "live"
    live.mkdir()
    tok = ByteBPETokenizer()
    tok.train(PT * 30, vocab_size=400)
    tok.save(live / "tokenizer.json")
    (live / "model_best.npz").write_bytes(b"TITULAR")
    return live


def _train_fn_factory():
    calls = {}

    def train_fn(dataset, init_from, out_dir, *, steps, **kw):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "model_best.npz").write_bytes(b"CANDIDATO")
        calls["steps"] = steps
        return {"best_val": 0.0}

    train_fn.calls = calls
    return train_fn


def _blind_eval_fn_factory(vitorias: dict):
    """vitorias: {"CANDIDATO": range/lista de ÍNDICES vencidos, "TITULAR": …}.

    O portão é pareado (E5): o que decide não é a média, é em QUAIS perguntas
    cada um ganhou. Por isso o fake devolve o veredito por pergunta (`rounds`)
    — só assim dá pra montar discordância a favor e contra."""
    def blind_eval_fn(ckpt_dir, questions):
        content = (Path(ckpt_dir) / "model_best.npz").read_bytes()
        for tag, idx in vitorias.items():
            if tag.encode() in content:
                ganhou = set(idx)
                rounds = [{"i": i, "winner": "nano" if i in ganhou else "teacher"}
                          for i in range(len(questions))]
                n_wins = sum(1 for r in rounds if r["winner"] == "nano")
                wr = round(100 * n_wins / len(questions), 1) if questions else 0.0
                return {"status": "ok", "nano_win_rate": wr, "n": len(questions),
                        "wins": {"nano": n_wins, "teacher": len(questions) - n_wins,
                                 "tie": 0},
                        "rounds": rounds}
        return {"status": "skipped", "reason": "desconhecido"}
    return blind_eval_fn


def test_sem_dataset_pula(tmp_path):
    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=tmp_path / "sem_dataset",
        work_root=tmp_path / "work", experiment_log_path=tmp_path / "hist.jsonl")
    assert res["status"] == "skipped"
    assert "dataset" in res["reason"]


def test_poucos_pares_pula(tmp_path):
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=10)
    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", experiment_log_path=tmp_path / "hist.jsonl",
        min_pairs=50)
    assert res["status"] == "skipped"
    assert "poucos pares" in res["reason"]


def test_sem_crescimento_desde_ultima_tentativa_pula(tmp_path):
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=300)
    hist = tmp_path / "hist.jsonl"
    from src.nanollm.experiment_log import log_experiment
    log_experiment(hist, name="answer_auto", base_ckpt="x", dataset="y",
                  hyperparams={"dataset_pairs": 250}, result={})
    # cresceu só 50 pares (300-250), abaixo do piso de 200
    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", experiment_log_path=hist,
        min_pairs=50, min_growth_pairs=200)
    assert res["status"] == "skipped"
    assert "cresceu só" in res["reason"]


def test_candidato_nao_supera_titular_rejeitado_e_registrado(tmp_path):
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=500)
    hist = tmp_path / "hist.jsonl"
    train_fn = _train_fn_factory()
    # o titular ganha em 20 perguntas; o candidato só em 6 delas → o delta
    # pareado é NEGATIVO
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": range(6),
                                            "TITULAR": range(20)})

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=60)

    assert res["status"] == "rejected"
    assert res["candidate_win_rate"] < res["incumbent_win_rate"]
    entries = read_experiment_history(hist)
    assert len(entries) == 1
    assert entries[0]["name"] == "answer_auto"
    assert entries[0]["result"]["promoted"] is False


def test_candidato_supera_titular_promovido_com_backup(tmp_path):
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=500)
    live = _live_ckpt(tmp_path)
    hist = tmp_path / "hist.jsonl"
    train_fn = _train_fn_factory()
    # candidato vence em 25 perguntas onde o titular perdeu, e em nenhuma o
    # contrário → p ≈ 6e-8, muito abaixo de α=0,05
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": range(25), "TITULAR": []})

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=live, dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=60)

    assert res["status"] == "promoted"
    assert res["teste_pareado"]["significativo"] is True
    # o titular (live) agora tem os pesos do candidato
    assert (live / "model_best.npz").read_bytes() == b"CANDIDATO"
    # backup do titular antigo existe (reversível)
    backup = Path(res["backup_dir"])
    assert (backup / "model_best.npz").read_bytes() == b"TITULAR"
    entries = read_experiment_history(hist)
    assert entries[-1]["result"]["promoted"] is True


def test_vantagem_pequena_nao_promove(tmp_path):
    """Candidato até ganha um pouco, mas o delta pareado pode ser sorteio —
    não promove. É o caso que a antiga margem de 5pp deixava passar quando o
    n era 15 (E5): o MESMO checkpoint oscilou 33,3%→46,7% sem mudar um peso."""
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=500)
    hist = tmp_path / "hist.jsonl"
    train_fn = _train_fn_factory()
    # 5 discordâncias a favor (0-4) e 4 contra (13-16) → p = 1,0
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": range(13),
                                            "TITULAR": range(5, 17)})

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=60)

    assert res["status"] == "rejected"
    assert res["candidate_win_rate"] > res["incumbent_win_rate"]   # ganhou…
    assert res["teste_pareado"]["significativo"] is False          # …mas pode ser sorteio


def test_conjunto_congelado_antes_do_treino(tmp_path):
    """E7: sem perguntas suficientes, pula ANTES de treinar 2000 passos."""
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=500)

    def _nao_treina(*a, **k):
        raise AssertionError("não devia treinar sem conjunto de perguntas")

    res = run_answer_flywheel(
        _FakeDB(n=5), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=tmp_path / "hist.jsonl", min_pairs=50,
        min_growth_pairs=200, train_fn=_nao_treina,
        blind_eval_fn=_blind_eval_fn_factory({"CANDIDATO": [0], "TITULAR": []}),
        min_questions=60)

    assert res["status"] == "skipped" and "poucas perguntas" in res["reason"]
