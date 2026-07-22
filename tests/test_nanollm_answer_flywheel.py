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
    def __init__(self, n=20):
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


def _blind_eval_fn_factory(win_rates: dict):
    """win_rates: {"CANDIDATO": x, "TITULAR": y} por conteúdo do model_best.npz."""
    def blind_eval_fn(ckpt_dir, questions):
        content = (Path(ckpt_dir) / "model_best.npz").read_bytes()
        for tag, wr in win_rates.items():
            if tag.encode() in content:
                return {"status": "ok", "nano_win_rate": wr, "n": len(questions),
                        "wins": {"nano": 0, "teacher": 0, "tie": 0}}
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
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": 20.0, "TITULAR": 33.3})

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=15)

    assert res["status"] == "rejected"
    assert res["candidate_win_rate"] == 20.0
    assert res["incumbent_win_rate"] == 33.3
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
    # candidato bate o titular com margem folgada (padrão margin=5.0pp)
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": 50.0, "TITULAR": 33.3})

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=live, dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=15)

    assert res["status"] == "promoted"
    # o titular (live) agora tem os pesos do candidato
    assert (live / "model_best.npz").read_bytes() == b"CANDIDATO"
    # backup do titular antigo existe (reversível)
    backup = Path(res["backup_dir"])
    assert (backup / "model_best.npz").read_bytes() == b"TITULAR"
    entries = read_experiment_history(hist)
    assert entries[-1]["result"]["promoted"] is True


def test_margem_insuficiente_nao_promove(tmp_path):
    """Candidato até ganha, mas por menos que a margem — não promove (evita
    trocar checkpoint por ruído de amostra, achado do M28/PLANO_CEREBRO_ASSUME)."""
    dataset = tmp_path / "dataset"
    _write_dataset(dataset, pairs=500)
    hist = tmp_path / "hist.jsonl"
    train_fn = _train_fn_factory()
    blind_eval_fn = _blind_eval_fn_factory({"CANDIDATO": 36.0, "TITULAR": 33.3})  # +2.7pp < margin 5.0

    res = run_answer_flywheel(
        _FakeDB(), live_ckpt=_live_ckpt(tmp_path), dataset_dir=dataset,
        work_root=tmp_path / "work", questions_path=tmp_path / "q.json",
        experiment_log_path=hist, min_pairs=50, min_growth_pairs=200,
        train_fn=train_fn, blind_eval_fn=blind_eval_fn, min_questions=15, margin=5.0)

    assert res["status"] == "rejected"


# ── E4: a resposta do Nano não pode chegar VAZIA ao juiz ──────────────────
def test_first_answer_block_nao_engole_resposta_que_comeca_com_quebra():
    """O Nano quase sempre começa a completion de 'Resposta:' com '\n\n'.
    Com `split` antes do `strip`, o juiz recebia string vazia (E4)."""
    from src.nanollm.flywheel import first_answer_block

    assert first_answer_block("\n\nUm engenheiro sênior faz X.\n\nOutro parágrafo") == \
        "Um engenheiro sênior faz X."
    assert first_answer_block(" \n\n  Resposta direta.  ") == "Resposta direta."
    assert first_answer_block("Sem quebra nenhuma") == "Sem quebra nenhuma"
    assert first_answer_block("") == ""          # vazio de verdade continua vazio
    assert first_answer_block(None) == ""


def test_blind_eval_do_flywheel_entrega_resposta_nao_vazia_ao_juiz(tmp_path, monkeypatch):
    """Caminho REAL de `_default_answer_blind_eval` (só o motor e o juiz são
    fakes): o que chega ao juiz tem que ser o texto do Nano, não ''."""
    import src.nanollm.blind_eval as be
    import src.nanollm.engine as eng
    import src.nanollm.flywheel as fw

    ckpt = tmp_path / "ckpt"
    ckpt.mkdir()
    (ckpt / "model_best.npz").write_bytes(b"X")

    class _FakeEngine:
        def __init__(self, ckpt_dir=None):
            self.ckpt_dir = ckpt_dir

        def available(self):
            return True

        def complete(self, prompt, max_tokens=60, **kw):
            return {"text": "\n\nUm engenheiro sênior revisa o código.\n\nsobra"}

    vistos = []

    def _fake_judge():
        def judge_fn(q, a, b):
            vistos.append((a, b))
            return "A"
        return judge_fn

    monkeypatch.setattr(eng, "NanoEngine", _FakeEngine)
    monkeypatch.setattr(be, "make_llm_judge", _fake_judge)
    monkeypatch.setattr(fw, "make_llm_teacher",
                        lambda **kw: (lambda q: "Resposta do professor."))

    res = fw._default_answer_blind_eval(ckpt, ["O que faz um engenheiro sênior?"])

    assert res["status"] == "ok"
    nano_resp = "Um engenheiro sênior revisa o código."
    assert any(nano_resp in a or nano_resp in b for a, b in vistos)
    assert all(a.strip() and b.strip() for a, b in vistos)   # nenhum lado vazio
