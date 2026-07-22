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
# Piso ÚNICO de pares para treinar (E16). Antes o scheduler noturno usava 5, a
# lib 12 e a rota outro valor conforme o caminho — 400 passos com 5 pares é
# overfit garantido, e ainda alimentava o val minúsculo do E1b. Um número só,
# aqui, usado por app/rota/CLI; `FLYWHEEL_MIN_PAIRS` no ambiente ajusta (lido a
# cada chamada, então mudar o .env não exige reiniciar).
FALLBACK_MIN_PAIRS = 50


def default_min_pairs() -> int:
    """Piso de pares do projeto — o MESMO em todos os caminhos (E16)."""
    return int(os.getenv("FLYWHEEL_MIN_PAIRS", FALLBACK_MIN_PAIRS))
DEFAULT_ANSWER_DATASET = "data/nano/distill_answers"
DEFAULT_BLIND_QUESTIONS = "data/nano/blind_eval_questions.json"
DEFAULT_EXPERIMENT_LOG = "data/nano/experiment_history.jsonl"
# Gabarito do professor por pergunta (E5): mesma referência para candidato,
# titular e todas as noites futuras.
DEFAULT_TEACHER_CACHE = "data/nano/blind_eval_teacher_cache.json"
# Held-out congelado da tarefa de TÍTULO (E6) — excluído do treino.
DEFAULT_TITLE_MESSAGES = "data/nano/title_eval_messages.json"


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
    """Perplexidade do checkpoint no val destilado: `{"val": <ppl float>}`.

    NÃO é mais o portão de promoção (ver E6 e `_title_gate`) — segue como
    número INFORMATIVO no ledger, porque continua útil para diagnosticar
    treino (divergiu? não aprendeu nada?).

    `evaluate()` devolve `report["val"]` como DICT (`{"nll":…, "ppl":…}`); passar
    isso adiante fazia `float(dict)` → TypeError, DEPOIS de treinar o candidato
    por 400 passos, toda noite em que houvesse pares suficientes (E1). Aqui o
    dict vira o número escalar, e `write_report=False` evita sobrescrever o
    relatório oficial do checkpoint vivo (E12)."""
    from src.nanollm.eval import evaluate
    report = evaluate(ckpt_dir, data_dir, probes=False, write_report=False)
    return {"val": float(report["val"]["ppl"]), "report": report}


def _title_gate(ckpt_dir: Path, items: list[str]) -> dict:
    """Portão da TAREFA de título: taxa de aceitação num held-out congelado."""
    from src.nanollm.title_eval import title_gate_accept
    return title_gate_accept(ckpt_dir, items)


def _answer_gate(ckpt_dir: Path, items: list[str]) -> dict:
    """Portão da tarefa de RESPOSTA: blind-eval pareado contra o professor."""
    res = _default_answer_blind_eval(Path(ckpt_dir), items)
    if res.get("status") == "ok":
        res["ok_por_item"] = {r["i"]: r["winner"] == "nano" for r in res["rounds"]}
        res["accept_rate"] = res["nano_win_rate"]
    return res


def _gate_items(db, source: str, questions_path, title_messages_path,
                min_items: int) -> list[str]:
    """Conjunto congelado de avaliação da tarefa, conforme a fonte."""
    if source == "reactions":
        from src.nanollm.blind_eval import freeze_questions
        return freeze_questions(db, questions_path, min_questions=min_items)
    from src.nanollm.title_eval import freeze_title_messages
    return freeze_title_messages(db, title_messages_path, n=min_items,
                                 min_messages=min_items)


def _gate_flags(res: dict) -> dict[int, bool]:
    """Veredito por item, no formato do teste pareado."""
    if "ok_por_item" in res:
        return res["ok_por_item"]
    return {r["i"]: bool(r.get("ok")) for r in res.get("rounds", [])}


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
    gate_fn: Callable[..., dict] | None = None,
    min_pairs: int | None = None,
    min_val_tokens: int = 512,
    min_gate_items: int = 20,
    steps: int = 400,
    alpha: float = 0.05,
    limit: int = 300,
    questions_path: str | Path = DEFAULT_BLIND_QUESTIONS,
    title_messages_path: str | Path = DEFAULT_TITLE_MESSAGES,
    promote: bool = True,
    now: datetime | None = None,
) -> dict:
    """Roda um ciclo do flywheel. Retorna um resumo (também gravado no ledger).

    `source` escolhe a FONTE dos pares (tarefas isoladas de propósito — lição
    do M14.2, nunca misturar distribuições):
    - "title" (padrão): o professor (Qwen) rotula as conversas reais.
    - "reactions": os 👍 do Leo já são o rótulo — sem chamar o professor.

    **O portão mede a TAREFA, não a perplexidade** (E6). O candidato treina na
    mesma distribuição do val destilado, então quase sempre "ganha" no ppl — e
    três experimentos manuais do projeto mediram ppl melhorando com a qualidade
    real PIORANDO. Agora vale a métrica de produto, num conjunto congelado e
    HELD-OUT (excluído do treino): taxa de aceitação do portão de título
    (`title_ok`+`title_relevant`) para `source="title"`, blind-eval pareado
    para `source="reactions"`. Promoção exige delta pareado significativo
    (p ≤ `alpha`), nunca "ganhou por pouco". A ppl continua sendo medida e
    registrada — como diagnóstico, não como juiz.

    `status`: "skipped" (pouco dado / sem titular), "rejected" (candidato não
    superou) ou "promoted". A decisão é sempre medida, nunca cega."""
    from src.nanollm.blind_eval import paired_sign_test
    min_pairs = default_min_pairs() if min_pairs is None else min_pairs
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

    # 0) Conjunto de avaliação da TAREFA, congelado, ANTES de qualquer treino:
    #    sem ele não há como decidir, e descobrir isso depois custaria uma noite
    #    de CPU (E7). Para título, ele também sai do treino (held-out de verdade).
    try:
        gate_items = _gate_items(db, source, questions_path, title_messages_path,
                                 min_gate_items)
    except ValueError as e:
        summary["reason"] = str(e)
        return _log(work_root, summary)
    summary["gate_items"] = len(gate_items)

    # 1) Destila as entradas reais no formato do fine-tune — a fonte depende
    #    de `source`: "title" chama o professor; "reactions" não precisa (o
    #    veredito do Leo já é o rótulo).
    dataset = work / "dataset"
    try:
        if source == "reactions":
            meta = run_reaction_distillation(db, tokenizer, dataset, limit=limit)
        else:
            teacher = teacher_fn or make_llm_teacher()
            meta = run_distillation(db, tokenizer, dataset, teacher_fn=teacher,
                                    limit=limit, exclude=set(gate_items))
    except ValueError as e:
        summary["reason"] = str(e)
        return _log(work_root, summary)

    summary["pairs"] = meta["pairs"]
    summary["inputs_seen"] = meta.get("inputs_seen")
    if meta["pairs"] < min_pairs:
        summary["reason"] = f"poucos pares ({meta['pairs']} < {min_pairs}) — junte mais conversas"
        return _log(work_root, summary)

    # 1b) Val curto demais → a medição do passo 3 vira ruído (uma janela parcial
    #     de ~60 tokens não decide nada). Melhor pular ANTES de queimar CPU do
    #     que treinar 400 passos e promover com base em nada (E1b).
    val_tokens = int(meta.get("val_tokens", 0))
    summary["val_tokens"] = val_tokens
    if val_tokens < min_val_tokens:
        summary["reason"] = (f"val destilado com {val_tokens} tokens (< {min_val_tokens}) — "
                             f"medição de ppl não seria confiável; esperando mais dado")
        return _log(work_root, summary)

    # 2) Treina o CANDIDATO a partir do titular (warm-start).
    candidate = work / "candidate"
    train = train_fn or _default_train
    train(dataset, live, candidate, steps=steps)

    summary["candidate_dir"] = str(candidate)

    # 3) Mede a TAREFA nos dois checkpoints, no mesmo conjunto congelado.
    gate = gate_fn or (_answer_gate if source == "reactions" else _title_gate)
    cand_res = gate(candidate, gate_items)
    base_res = gate(live, gate_items)
    if cand_res.get("status") != "ok" or base_res.get("status") != "ok":
        summary["reason"] = (f"portão da tarefa não rodou: "
                             f"{cand_res.get('reason') or base_res.get('reason')}")
        return _log(work_root, summary)

    teste = paired_sign_test(_gate_flags(cand_res), _gate_flags(base_res), alpha=alpha)
    summary.update({"candidate_accept": cand_res.get("accept_rate"),
                    "incumbent_accept": base_res.get("accept_rate"),
                    "teste_pareado": teste})

    # 3b) Perplexidade: diagnóstico, NÃO juiz (E6). Se falhar, não derruba o
    #     ciclo — a decisão não depende dela.
    try:
        ev = eval_fn or _default_eval
        summary["candidate_val"] = float(ev(candidate, dataset)["val"])
        summary["incumbent_val"] = float(ev(live, dataset)["val"])
    except Exception as e:
        logger.info(f"[flywheel] ppl informativa não pôde ser medida: {e}")

    if not (teste["significativo"] and promote):
        summary["status"] = "rejected"
        summary["reason"] = (
            f"tarefa: candidato {cand_res.get('accept_rate')}% vs titular "
            f"{base_res.get('accept_rate')}% — delta pareado não significativo "
            f"(ganhou {teste['candidato_ganhou']}, perdeu {teste['titular_ganhou']} "
            f"de {teste['discordantes']} discordantes, p={teste['p_value']} > α={alpha})")
        logger.info(f"[flywheel] rejeitado: {summary['reason']}")
        return _log(work_root, summary)

    # 4) Promove — mas primeiro faz backup do titular (reversível).
    backup = work / "prev_live"
    summary["backup_dir"] = str(backup)
    _copy_model_files(live, backup)
    promoted = _copy_model_files(candidate, live)
    summary["status"] = "promoted"
    summary["promoted_files"] = promoted
    summary["gain"] = round((cand_res.get("accept_rate") or 0)
                            - (base_res.get("accept_rate") or 0), 1)
    logger.info(f"[flywheel] PROMOVIDO: tarefa {base_res.get('accept_rate')}% → "
                f"{cand_res.get('accept_rate')}% (p={teste['p_value']}); "
                f"backup em {backup}")
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


def first_answer_block(completion: str) -> str:
    """Primeiro bloco da completion — a resposta que vai ao juiz.

    O `strip()` vem ANTES do `split`: o Nano quase sempre começa a completion de
    `"…\\n\\nResposta:"` com uma quebra dupla, e `split("\\n\\n")[0]` pegava o
    trecho ANTES dela — isto é, string vazia. O juiz recebia uma resposta vazia
    do Nano e o win-rate registrado ficava contaminado (E4)."""
    return (completion or "").strip().split("\n\n")[0].strip()


def _default_answer_blind_eval(ckpt_dir: Path, questions: list[str],
                               max_tokens: int = 80,
                               teacher_cache: str | Path = DEFAULT_TEACHER_CACHE) -> dict:
    """Win-rate real do checkpoint contra o professor, no conjunto congelado —
    mesma medição usada nas rodadas manuais (Pergunta:/Resposta:, motor real).

    Duas garantias do E5 vivem aqui: o professor vem do GABARITO em disco
    (candidato e titular comparados contra a MESMA referência) e o juiz vota
    duas vezes com as posições trocadas (`two_pass`)."""
    from src.nanollm.blind_eval import blind_compare, cached_teacher, make_llm_judge
    from src.nanollm.engine import NanoEngine

    engine = NanoEngine(ckpt_dir=ckpt_dir)
    if not engine.available():
        return {"status": "skipped", "reason": f"sem checkpoint em {ckpt_dir}"}

    def nano_fn(q: str) -> str:
        # stop em "Pergunta:" (E13): o modelo base tende a emendar uma pergunta
        # nova depois da resposta — o juiz não deve ver esse rabicho.
        out = engine.complete(f"Pergunta: {q}\n\nResposta:", max_tokens=max_tokens,
                              stop=["Pergunta:", "\nP:"]).get("text", "")
        return first_answer_block(out)

    teacher = cached_teacher(make_llm_teacher(max_tokens=max_tokens), teacher_cache)
    judge = make_llm_judge()
    res = blind_compare(questions, nano_fn, teacher, judge, seed=0, two_pass=True)
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
    min_pairs: int | None = None,
    min_growth_pairs: int = 200,
    steps: int = 2000,
    lr: float = 2e-4,
    patience: int = 5,
    freeze_blocks: int = 0,
    alpha: float = 0.05,
    min_questions: int = 60,
    train_fn: Callable[..., dict] | None = None,
    blind_eval_fn: Callable[..., dict] | None = None,
    promote: bool = True,
    now: datetime | None = None,
) -> dict:
    """Fine-tune de resposta noturno com portão de BLIND-EVAL (não ppl).

    Só treina quando o corpus de destilação (`dataset_dir`) cresceu pelo menos
    `min_growth_pairs` desde a última tentativa AUTOMÁTICA registrada (não
    starta do zero a cada noite — 3 experimentos manuais já mostraram que
    repetir com pouco dado novo não ajuda).

    Promoção passa por **teste estatístico pareado** (`paired_win_test`), não
    mais por "ganhou por 5 pontos percentuais": com n=15 o mesmo checkpoint
    marcou 33,3% e 46,7% em noites diferentes sem mudar um peso, então margem
    fixa promovia ruído (E5). Agora exige-se que o delta pareado seja
    improvável ao acaso (p ≤ `alpha`) num conjunto de pelo menos
    `min_questions` perguntas congeladas. Cada tentativa (promovida ou não) é
    registrada no histórico de experimentos."""
    from src.nanollm.experiment_log import log_experiment, read_experiment_history

    min_pairs = default_min_pairs() if min_pairs is None else min_pairs
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

    # O conjunto de perguntas é congelado ANTES do treino: sem ele não há como
    # medir, e treinar 2000 passos para descobrir isso depois é queimar horas
    # de CPU toda noite em que a condição persistir (E7).
    from src.nanollm.blind_eval import freeze_questions, paired_win_test
    try:
        questions = freeze_questions(db, questions_path, min_questions=min_questions)
    except ValueError as e:
        summary["reason"] = str(e)
        return _log(work_root, summary)

    candidate = work / "candidate"
    train = train_fn or _default_answer_train
    train(dataset, live, candidate, steps=steps, lr=lr, patience=patience,
          freeze_blocks=freeze_blocks)

    blind_eval = blind_eval_fn or _default_answer_blind_eval
    cand_res = blind_eval(candidate, questions)
    base_res = blind_eval(live, questions)
    if cand_res.get("status") != "ok" or base_res.get("status") != "ok":
        summary["reason"] = "blind-eval não rodou (checkpoint indisponível)"
        return _log(work_root, summary)

    cand_wr, base_wr = cand_res["nano_win_rate"], base_res["nano_win_rate"]
    teste = paired_win_test(cand_res.get("rounds", []), base_res.get("rounds", []),
                            alpha=alpha)
    summary.update({"candidate_win_rate": cand_wr, "incumbent_win_rate": base_wr,
                    "candidate_dir": str(candidate), "n_questions": len(questions),
                    "teste_pareado": teste})
    hyperparams = {"lr": lr, "steps_budget": steps, "patience": patience,
                   "freeze_blocks": freeze_blocks, "dataset_pairs": pairs}
    result = {"candidate_win_rate": cand_wr, "incumbent_win_rate": base_wr,
              "teste_pareado": teste}

    improved = teste["significativo"]
    if not (improved and promote):
        summary["status"] = "rejected"
        summary["reason"] = (
            f"candidato {cand_wr}% vs titular {base_wr}%: delta pareado não é "
            f"significativo (ganhou {teste['candidato_ganhou']}, perdeu "
            f"{teste['titular_ganhou']} das {teste['discordantes']} discordantes, "
            f"p={teste['p_value']} > α={alpha}) — pode ser sorteio")
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
                   notes=(f"promovido: {cand_wr}% > {base_wr}% com delta pareado "
                          f"significativo (p={teste['p_value']} ≤ α={alpha})"))
    logger.info(f"[flywheel-resposta] PROMOVIDO: win-rate {base_wr}% → {cand_wr}% "
                f"(p={teste['p_value']}); backup em {backup}")
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
    p.add_argument("--min-pairs", type=int, default=None,
                   help="mínimo de pares p/ treinar (padrão único do projeto)")
    p.add_argument("--limit", type=int, default=300, help="máx. de conversas a destilar")
    p.add_argument("--seed", type=int, default=1337)
    args = p.parse_args(argv)

    from src.storage import DatabaseManager

    res = run_nightly_flywheel(DatabaseManager(), source=args.source, steps=args.steps,
                               min_pairs=args.min_pairs, limit=args.limit)
    st = res.get("status")
    if st == "promoted":
        teste = res.get("teste_pareado", {})
        print(f"✓ PROMOVIDO — tarefa {res.get('incumbent_accept')}% → "
              f"{res.get('candidate_accept')}% em {res.get('gate_items')} itens "
              f"congelados (p={teste.get('p_value')}); {res.get('pairs')} pares. "
              f"Reinicie/recarregue p/ servir o novo cérebro.")
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
