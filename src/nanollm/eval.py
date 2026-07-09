"""Harness de avaliação do Apolo-Nano (Épico 1.3) — a régua entre runs.

Três medidas, todas DETERMINÍSTICAS e comparáveis entre checkpoints:

1. **Perplexity de validação** — NLL média por token sobre janelas FIXAS e
   sequenciais do val.npy (sem sorteio; mesmo val = mesmo número).
2. **Amostras-sonda** — os MESMOS 10 prompts versionados (PROBES_V1), gerados
   com seed fixa; a evolução da qualidade fica legível run a run.
3. **Relatório** — JSON por run (config, params, passo, ppl, sondas, tempo) em
   `<ckpt>/eval_report.json` + histórico acumulado em `<ckpt>/evals.jsonl`.

Uso:
    python -m src.nanollm.eval --ckpt data/nanollm/ckpt_real --data data/nanollm
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from src.nanollm.generate import load_model_and_tokenizer
from src.nanollm.model import GPT

# Sondas versionadas: NUNCA edite uma lista publicada — crie PROBES_V2.
PROBES_V1: list[str] = [
    "O Apolo é",
    "Tópico: Python\n",
    "## Conceitos-chave\n",
    "A inteligência artificial",
    "Para melhorar a qualidade do código,",
    "O aprendizado de máquina",
    "A segurança da informação exige",
    "Categoria: backend\n\n",
    "Os dados são",
    "Em resumo,",
]
PROBES_VERSION = "v1"
_PROBE_SEED = 20260709
_PROBE_TOKENS = 60


def perplexity(model: GPT, tokens: np.ndarray, batch_size: int = 8,
               max_windows: int = 200) -> dict:
    """NLL média por token em janelas sequenciais fixas → ppl = exp(nll).

    Janelas não-sobrepostas de block_size+1 (x = janela[:-1], y = janela[1:]),
    começando do token 0 — determinístico por construção.
    """
    block = model.config.block_size
    step = block + 1
    n_windows = min((len(tokens) - 1) // step, max_windows)
    if n_windows < 1:
        raise ValueError(f"val com {len(tokens)} tokens < janela de {step}")
    nlls: list[float] = []
    for start in range(0, n_windows * step, step * batch_size):
        rows = []
        for w in range(batch_size):
            i = start + w * step
            if i + step > n_windows * step:
                break
            rows.append(tokens[i : i + step].astype(np.int64))
        if not rows:
            break
        batch = np.stack(rows)
        _, loss = model.forward(batch[:, :-1], batch[:, 1:])
        model._probs = None  # avaliação: descarta cache de backward
        model._targets = None
        nlls.extend([loss] * len(rows))  # janelas de tamanho igual → média simples
    nll = float(np.mean(nlls))
    return {"nll": round(nll, 4), "ppl": round(float(np.exp(nll)), 2),
            "windows": len(nlls), "tokens_avaliados": len(nlls) * block}


def run_probes(model: GPT, tok, n_tokens: int = _PROBE_TOKENS) -> list[dict]:
    """Gera as sondas com seed fixa — mesmo checkpoint → mesmas saídas."""
    out = []
    for i, prompt in enumerate(PROBES_V1):
        ids = tok.encode(prompt) or [tok.sep_id]
        rng = np.random.default_rng(_PROBE_SEED + i)
        gen = model.generate(np.array([ids], dtype=np.int64), n_tokens,
                             temperature=0.8, top_k=40, rng=rng, stop_id=tok.sep_id)
        new = [int(t) for t in gen[0, len(ids):] if int(t) != tok.sep_id]
        out.append({"prompt": prompt, "texto": tok.decode(new)})
    return out


def evaluate(ckpt_dir: str | Path, data_dir: str | Path, probes: bool = True) -> dict:
    """Avalia um checkpoint e persiste o relatório. Retorna o dict do run."""
    ckpt = Path(ckpt_dir)
    data = Path(data_dir)
    model, tok = load_model_and_tokenizer(ckpt)

    t0 = time.time()
    val = np.load(data / "val.npy", mmap_mode="r")
    ppl = perplexity(model, val)

    state = {}
    state_file = ckpt / "state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))

    report = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ckpt": str(ckpt),
        "params_m": round(model.num_params / 1e6, 3),
        "config": asdict(model.config),
        "passo_treino": state.get("step"),
        "val": ppl,
        "probes_version": PROBES_VERSION,
        "sondas": run_probes(model, tok) if probes else [],
        "duracao_s": None,  # preenchido abaixo
    }
    report["duracao_s"] = round(time.time() - t0, 1)

    (ckpt / "eval_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    resumo = {k: report[k] for k in ("quando", "params_m", "passo_treino", "val")}
    with (ckpt / "evals.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(resumo, ensure_ascii=False) + "\n")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Avalia um checkpoint do Apolo-Nano")
    ap.add_argument("--ckpt", default="data/nanollm/ckpt")
    ap.add_argument("--data", default="data/nanollm")
    ap.add_argument("--no-probes", action="store_true")
    args = ap.parse_args()
    report = evaluate(args.ckpt, args.data, probes=not args.no_probes)
    print(f"params: {report['params_m']}M | passo: {report['passo_treino']} | "
          f"val ppl: {report['val']['ppl']} (nll {report['val']['nll']}) | "
          f"{report['val']['windows']} janelas em {report['duracao_s']}s")
    for s in report["sondas"][:3]:
        print(f"\n>>> {s['prompt']!r}\n{s['texto'][:200]}")


if __name__ == "__main__":
    main()
