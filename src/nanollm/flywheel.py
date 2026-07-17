"""Flywheel noturno (M25.3) — o Nano melhora sozinho, de madrugada, só se de fato melhorar.

Fecha o ciclo do M25: destila (M25.2) → treina um CANDIDATO a partir do
checkpoint vivo (warm-start) → avalia candidato E titular no MESMO conjunto de
validação → PROMOVE só se o candidato ganhar. É a "roda-viva": cada noite o Nano
imita melhor o professor nas entradas reais do Leo, e assume mais um pedaço.

Princípios (honestos e reversíveis):
- **Portão de qualidade**: promoção exige que a perplexidade do candidato no val
  destilado seja MENOR que a do titular pelo mesmo teste. Sem melhora medida,
  nada muda — o titular continua servindo.
- **Reversível**: antes de promover, o modelo vivo é copiado para um backup
  datado; `revert_promotion` desfaz.
- **Testável**: `train_fn`/`eval_fn`/`teacher_fn` são injetáveis. Os testes usam
  fakes (sem NumPy pesado, sem LLM) e exercitam TODA a decisão de promoção.
- **Barato de pular**: sem pares suficientes (conversas de menos), retorna
  `skipped` sem treinar — não queima CPU à toa.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.nanollm.distill import make_llm_teacher, run_distillation, run_reaction_distillation

logger = logging.getLogger("apolo.nano.flywheel")

DEFAULT_WORK_ROOT = "data/nano/flywheel"


def _default_live_ckpt() -> Path:
    return Path(os.getenv("NANO_CKPT", "data/nanollm/ckpt_v1"))


def _default_train(data_dir: Path, init_from: Path, out_dir: Path, *,
                   steps: int, seed: int = 1337) -> dict:
    """Fine-tune warm-start real do Nano (import preguiçoso — só quem roda paga)."""
    import argparse

    from src.nanollm.train import train
    args = argparse.Namespace(
        data=str(data_dir), out=str(out_dir), preset="small",
        steps=steps, batch_size=8, lr=3e-4, warmup=min(50, max(1, steps // 5)),
        weight_decay=0.01, grad_clip=1.0, log_every=50,
        eval_every=max(50, steps // 4), eval_iters=10, seed=seed,
        resume=False, init_from=str(init_from),
    )
    return train(args)


def _default_eval(ckpt_dir: Path, data_dir: Path) -> dict:
    from src.nanollm.eval import evaluate
    return evaluate(ckpt_dir, data_dir, probes=False)


def _copy_model_files(src: Path, dst: Path) -> list[str]:
    """Copia os pesos (model*.npz) de src→dst. Devolve o que copiou."""
    dst.mkdir(parents=True, exist_ok=True)
    copied = []
    for name in ("model_best.npz", "model.npz", "state.json"):
        f = src / name
        if f.exists():
            shutil.copy2(f, dst / name)
            copied.append(name)
    return copied


def revert_promotion(live_ckpt: str | Path, backup_dir: str | Path) -> list[str]:
    """Desfaz a última promoção: restaura os pesos do backup para o checkpoint vivo."""
    restored = _copy_model_files(Path(backup_dir), Path(live_ckpt))
    logger.info(f"[flywheel] revertido {live_ckpt} ← {backup_dir}: {restored}")
    return restored


def run_nightly_flywheel(
    db,
    *,
    live_ckpt: str | Path | None = None,
    work_root: str | Path = DEFAULT_WORK_ROOT,
    source: str = "title",
    teacher_fn: Callable[[str], str] | None = None,
    train_fn: Callable[..., dict] | None = None,
    eval_fn: Callable[..., dict] | None = None,
    min_pairs: int = 12,
    steps: int = 400,
    margin: float = 0.0,
    limit: int = 300,
    promote: bool = True,
    now: datetime | None = None,
) -> dict:
    """Roda um ciclo do flywheel. Retorna um resumo (também gravado no ledger).

    `source` escolhe a FONTE dos pares (tarefas isoladas de propósito — lição
    do M14.2, nunca misturar distribuições):
    - "title" (padrão): o professor (Qwen) rotula as conversas reais.
    - "reactions": os 👍 do Leo já são o rótulo — sem chamar o professor.

    `status`: "skipped" (pouco dado / sem titular), "rejected" (candidato não
    superou) ou "promoted". A decisão é sempre medida, nunca cega."""
    live = Path(live_ckpt) if live_ckpt else _default_live_ckpt()
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    # A fonte entra no nome da pasta: duas rodadas na MESMA noite (título +
    # reações, chamadas em sequência) caem no mesmo segundo com frequência —
    # sem isso, colidiriam no mesmo diretório de trabalho e uma sobrescreveria
    # o dataset/candidato da outra.
    work = Path(work_root) / f"{stamp}_{source}"
    tokenizer = live / "tokenizer.json"

    summary: dict = {"quando": stamp, "status": "skipped", "live_ckpt": str(live),
                     "source": source}

    if not tokenizer.exists():
        summary["reason"] = f"sem tokenizer em {tokenizer} — treine o Nano v1 primeiro"
        return _log(work_root, summary)

    # 1) Destila as entradas reais no formato do fine-tune — a fonte depende
    #    de `source`: "title" chama o professor; "reactions" não precisa (o
    #    veredito do Leo já é o rótulo).
    dataset = work / "dataset"
    try:
        if source == "reactions":
            meta = run_reaction_distillation(db, tokenizer, dataset, limit=limit)
        else:
            teacher = teacher_fn or make_llm_teacher()
            meta = run_distillation(db, tokenizer, dataset, teacher_fn=teacher, limit=limit)
    except ValueError as e:
        summary["reason"] = str(e)
        return _log(work_root, summary)

    summary["pairs"] = meta["pairs"]
    summary["inputs_seen"] = meta.get("inputs_seen")
    if meta["pairs"] < min_pairs:
        summary["reason"] = f"poucos pares ({meta['pairs']} < {min_pairs}) — junte mais conversas"
        return _log(work_root, summary)

    # 2) Treina o CANDIDATO a partir do titular (warm-start).
    candidate = work / "candidate"
    train = train_fn or _default_train
    train(dataset, live, candidate, steps=steps)

    # 3) Mede candidato E titular no MESMO val destilado — o portão honesto.
    ev = eval_fn or _default_eval
    cand_val = float(ev(candidate, dataset)["val"])
    base_val = float(ev(live, dataset)["val"])
    summary.update({"candidate_val": cand_val, "incumbent_val": base_val,
                    "candidate_dir": str(candidate)})

    improved = cand_val < base_val - margin
    if not (improved and promote):
        summary["status"] = "rejected"
        summary["reason"] = (f"candidato {cand_val:.4f} não superou titular "
                             f"{base_val:.4f} (margem {margin})")
        logger.info(f"[flywheel] rejeitado: {summary['reason']}")
        return _log(work_root, summary)

    # 4) Promove — mas primeiro faz backup do titular (reversível).
    backup = work / "prev_live"
    summary["backup_dir"] = str(backup)
    _copy_model_files(live, backup)
    promoted = _copy_model_files(candidate, live)
    summary["status"] = "promoted"
    summary["promoted_files"] = promoted
    summary["gain"] = round(base_val - cand_val, 4)
    logger.info(f"[flywheel] PROMOVIDO: val {base_val:.4f} → {cand_val:.4f} "
                f"(ganho {summary['gain']}); backup em {backup}")
    return _log(work_root, summary)


def _log(work_root: str | Path, summary: dict) -> dict:
    """Anexa o resumo ao ledger do flywheel (uma linha por noite)."""
    try:
        root = Path(work_root)
        root.mkdir(parents=True, exist_ok=True)
        with (root / "flywheel_log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[flywheel] não consegui gravar o ledger: {e}")
    return summary


# ── Flywheel de RESPOSTA (item 2 do PLANO_FLYWHEEL_AUTOMATICO.md) ──────────
# Deliberadamente SEPARADO de `run_nightly_flywheel`: aquele promove por
# PERPLEXIDADE no val destilado — achado real de 3 experimentos manuais
# (PLANO_CORPUS_DIVERSO.md): ppl melhorou mas o BLIND-EVAL mostrou piora nos
# três. Reusar o gate por ppl aqui repetiria o mesmo erro, só que automático e
# sem ninguém olhando. Este flywheel promove só por blind-eval real (win-rate
# no conjunto congelado de perguntas, contra o motor real de produção).
DEFAULT_ANSWER_DATASET = "data/nano/distill_answers"
DEFAULT_BLIND_QUESTIONS = "data/nano/blind_eval_questions.json"
DEFAULT_EXPERIMENT_LOG = "data/nano/experiment_history.jsonl"


def _default_answer_train(dataset_dir: Path, init_from: Path, out_dir: Path, *,
                          steps: int, lr: float, patience: int, freeze_blocks: int,
                          seed: int = 1337) -> dict:
    """Fine-tune warm-start real (import preguiçoso — só quem roda paga)."""
    import argparse

    from src.nanollm.train import train
    args = argparse.Namespace(
        data=str(dataset_dir), out=str(out_dir), preset="small", steps=steps,
        batch_size=8, lr=lr, warmup=min(50, max(1, steps // 10)), weight_decay=0.01,
        grad_clip=1.0, log_every=50, eval_every=25, eval_iters=10, seed=seed,
        resume=False, init_from=str(init_from), patience=patience,
        freeze_blocks=freeze_blocks,
    )
    return train(args)


def _default_answer_blind_eval(ckpt_dir: Path, questions: list[str],
                               max_tokens: int = 80) -> dict:
    """Win-rate real do checkpoint contra o professor, no conjunto congelado —
    mesma medição usada nas rodadas manuais (Pergunta:/Resposta:, motor real)."""
    from src.nanollm.blind_eval import blind_compare, make_llm_judge
    from src.nanollm.engine import NanoEngine

    engine = NanoEngine(ckpt_dir=ckpt_dir)
    if not engine.available():
        return {"status": "skipped", "reason": f"sem checkpoint em {ckpt_dir}"}

    def nano_fn(q: str) -> str:
        out = engine.complete(f"Pergunta: {q}\n\nResposta:", max_tokens=max_tokens).get("text", "")
        return out.split("\n\n")[0].strip()

    teacher = make_llm_teacher(max_tokens=max_tokens)
    judge = make_llm_judge()
    res = blind_compare(questions, nano_fn, teacher, judge, seed=0)
    res["status"] = "ok"
    return res


def run_answer_flywheel(
    db,
    *,
    live_ckpt: str | Path | None = None,
    dataset_dir: str | Path = DEFAULT_ANSWER_DATASET,
    work_root: str | Path = DEFAULT_WORK_ROOT,
    questions_path: str | Path = DEFAULT_BLIND_QUESTIONS,
    experiment_log_path: str | Path = DEFAULT_EXPERIMENT_LOG,
    min_pairs: int = 50,
    min_growth_pairs: int = 200,
    steps: int = 2000,
    lr: float = 2e-4,
    patience: int = 5,
    freeze_blocks: int = 0,
    margin: float = 5.0,
    min_questions: int = 15,
    train_fn: Callable[..., dict] | None = None,
    blind_eval_fn: Callable[..., dict] | None = None,
    promote: bool = True,
    now: datetime | None = None,
) -> dict:
    """Fine-tune de resposta noturno com portão de BLIND-EVAL (não ppl).

    Só treina quando o corpus de destilação (`dataset_dir`) cresceu pelo menos
    `min_growth_pairs` desde a última tentativa AUTOMÁTICA registrada (não
    starta do zero a cada noite — 3 experimentos manuais já mostraram que
    repetir com pouco dado novo não ajuda). Promove só se o candidato bater o
    titular no blind-eval real com margem (`margin` pontos percentuais) — cada
    tentativa (promovida ou não) é registrada no histórico de experimentos."""
    from src.nanollm.experiment_log import log_experiment, read_experiment_history

    live = Path(live_ckpt) if live_ckpt else _default_live_ckpt()
    dataset = Path(dataset_dir)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    work = Path(work_root) / f"{stamp}_answer"

    summary: dict = {"quando": stamp, "status": "skipped", "live_ckpt": str(live),
                     "source": "answer"}

    meta_path = dataset / "meta.json"
    if not meta_path.exists():
        summary["reason"] = f"sem dataset em {dataset} — rode a destilação de conhecimento primeiro"
        return _log(work_root, summary)
    pairs = json.loads(meta_path.read_text(encoding="utf-8")).get("pairs", 0)
    summary["dataset_pairs"] = pairs
    if pairs < min_pairs:
        summary["reason"] = f"poucos pares ({pairs} < {min_pairs})"
        return _log(work_root, summary)

    last_auto = [e for e in read_experiment_history(experiment_log_path, limit=200)
                if e.get("name") == "answer_auto"]
    last_pairs = last_auto[-1].get("hyperparams", {}).get("dataset_pairs", 0) if last_auto else 0
    if pairs - last_pairs < min_growth_pairs:
        summary["reason"] = (f"corpus cresceu só {pairs - last_pairs} pares desde a última "
                             f"tentativa automática (< {min_growth_pairs}) — esperando mais dado")
        return _log(work_root, summary)

    candidate = work / "candidate"
    train = train_fn or _default_answer_train
    train(dataset, live, candidate, steps=steps, lr=lr, patience=patience,
          freeze_blocks=freeze_blocks)

    from src.nanollm.blind_eval import freeze_questions
    try:
        questions = freeze_questions(db, questions_path, min_questions=min_questions)
    except ValueError as e:
        summary["reason"] = str(e)
        return _log(work_root, summary)

    blind_eval = blind_eval_fn or _default_answer_blind_eval
    cand_res = blind_eval(candidate, questions)
    base_res = blind_eval(live, questions)
    if cand_res.get("status") != "ok" or base_res.get("status") != "ok":
        summary["reason"] = "blind-eval não rodou (checkpoint indisponível)"
        return _log(work_root, summary)

    cand_wr, base_wr = cand_res["nano_win_rate"], base_res["nano_win_rate"]
    summary.update({"candidate_win_rate": cand_wr, "incumbent_win_rate": base_wr,
                    "candidate_dir": str(candidate), "n_questions": len(questions)})
    hyperparams = {"lr": lr, "steps_budget": steps, "patience": patience,
                   "freeze_blocks": freeze_blocks, "dataset_pairs": pairs}
    result = {"candidate_win_rate": cand_wr, "incumbent_win_rate": base_wr}

    improved = cand_wr > base_wr + margin
    if not (improved and promote):
        summary["status"] = "rejected"
        summary["reason"] = (f"candidato {cand_wr}% não superou titular {base_wr}% "
                             f"com margem {margin}pp")
        result["promoted"] = False
        log_experiment(experiment_log_path, name="answer_auto", base_ckpt=str(live),
                       dataset=str(dataset), hyperparams=hyperparams, result=result,
                       notes=summary["reason"])
        logger.info(f"[flywheel-resposta] rejeitado: {summary['reason']}")
        return _log(work_root, summary)

    backup = work / "prev_live"
    summary["backup_dir"] = str(backup)
    _copy_model_files(live, backup)
    summary["promoted_files"] = _copy_model_files(candidate, live)
    summary["status"] = "promoted"
    result["promoted"] = True
    log_experiment(experiment_log_path, name="answer_auto", base_ckpt=str(live),
                   dataset=str(dataset), hyperparams=hyperparams, result=result,
                   notes=f"promovido: {cand_wr}% > {base_wr}% (+{margin}pp)")
    logger.info(f"[flywheel-resposta] PROMOVIDO: win-rate {base_wr}% → {cand_wr}%; "
               f"backup em {backup}")
    return _log(work_root, summary)


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.nanollm.flywheel [--steps N] [--min-pairs K]`.
    Dispara UMA rodada AGORA (sem esperar as 3h): destila as conversas reais,
    treina um candidato e promove só se melhorar. Imprime o resultado."""
    import argparse

    p = argparse.ArgumentParser(description="Roda uma volta do flywheel do Nano (M25.3)")
    p.add_argument("--source", choices=("title", "reactions"), default="title",
                   help="title → o professor rotula; reactions → os 👍 do Leo já são o rótulo")
    p.add_argument("--steps", type=int, default=400, help="passos de treino do candidato")
    p.add_argument("--min-pairs", type=int, default=12, help="mínimo de pares p/ treinar")
    p.add_argument("--limit", type=int, default=300, help="máx. de conversas a destilar")
    p.add_argument("--seed", type=int, default=1337)
    args = p.parse_args(argv)

    from src.storage import DatabaseManager

    res = run_nightly_flywheel(DatabaseManager(), source=args.source, steps=args.steps,
                               min_pairs=args.min_pairs, limit=args.limit)
    st = res.get("status")
    if st == "promoted":
        print(f"✓ PROMOVIDO — perplexidade {res['incumbent_val']:.3f} → "
              f"{res['candidate_val']:.3f} (ganho {res.get('gain')}); "
              f"{res.get('pairs')} pares. Reinicie/recarregue p/ servir o novo cérebro.")
    elif st == "rejected":
        print(f"• candidato não superou o titular ({res.get('reason')}). Nada mudou.")
    else:
        print(f"• pulei: {res.get('reason')}")
    return 0


def read_flywheel_log(work_root: str | Path = DEFAULT_WORK_ROOT, limit: int = 20) -> list[dict]:
    """Últimas noites do flywheel (mais recentes primeiro) — para o painel/UI."""
    path = Path(work_root) / "flywheel_log.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    return list(reversed(out))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    raise SystemExit(main())
