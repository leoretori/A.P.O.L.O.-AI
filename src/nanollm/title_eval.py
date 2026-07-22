"""Régua da TAREFA de título: quantas mensagens reais o Nano consegue titular.

Por que existir (E6): o flywheel de título promovia por PERPLEXIDADE no val
destilado. O candidato treina exatamente naquela distribuição, então quase
sempre "ganha" no ppl — e o próprio projeto já mediu, em três experimentos
manuais, ppl melhorando enquanto a qualidade real PIORAVA
(PLANO_CORPUS_DIVERSO.md). O que decide promoção aqui é a métrica que o produto
usa de verdade: a taxa em que o portão determinístico
(`title_ok` + `title_relevant`) ACEITA o título gerado — o `gate_accept` que o
M26 usou à mão para decidir não promover o `ckpt_medium_v2`.

Determinístico: mesma seed por mensagem → mesmo veredito, run a run.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.nanollm.tasks import extract_title, title_ok, title_relevant, title_prompt

logger = logging.getLogger("apolo.nano.title_eval")

DEFAULT_TITLE_MESSAGES = "data/nano/title_eval_messages.json"


def title_gate_accept(ckpt_dir: str | Path, messages: list[str], *,
                      seed: int = 0, engine=None) -> dict:
    """Taxa de aceitação do portão de título para um checkpoint.

    Devolve `{"status", "accept_rate", "aceitos", "n", "rounds"}`. `rounds` traz
    o veredito POR MENSAGEM (`{"i", "ok", "title"}`) — é o que permite o teste
    pareado entre candidato e titular (as mesmas mensagens nos dois)."""
    if engine is None:
        from src.nanollm.engine import NanoEngine
        engine = NanoEngine(ckpt_dir=ckpt_dir)
    if not engine.available():
        return {"status": "skipped", "reason": f"sem checkpoint em {ckpt_dir}"}

    rounds = []
    for i, msg in enumerate(messages):
        try:
            out = engine.complete(title_prompt(msg), max_tokens=16, temperature=0.5,
                                  top_k=20, seed=seed + i).get("text", "")
            title = extract_title(out)
            ok = bool(title_ok(title) and title_relevant(title, msg))
        except Exception as e:                 # um checkpoint ruim não derruba a medição
            logger.debug(f"[title_eval] falhou na mensagem {i}: {e}")
            title, ok = "", False
        rounds.append({"i": i, "ok": ok, "title": title})

    aceitos = sum(1 for r in rounds if r["ok"])
    n = len(rounds)
    return {
        "status": "ok", "n": n, "aceitos": aceitos,
        "accept_rate": round(100 * aceitos / n, 1) if n else 0.0,
        "rounds": rounds,
    }


def freeze_title_messages(db, path: str | Path = DEFAULT_TITLE_MESSAGES,
                          *, n: int = 30, min_messages: int = 10) -> list[str]:
    """Congela o conjunto HELD-OUT de mensagens usado para medir a tarefa.

    Mesmo princípio do `freeze_questions` do blind-eval: uma vez congelado, não
    re-sorteia (senão duas noites medem exames diferentes e o delta não
    significa nada) — só CRESCE, mantendo as antigas na ordem. Estas mensagens
    são excluídas da destilação de treino (`run_distillation(exclude=…)`), para
    o candidato não ser avaliado no que acabou de decorar."""
    p = Path(path)
    congeladas: list[str] = []
    if p.exists():
        congeladas = json.loads(p.read_text(encoding="utf-8"))
        if len(congeladas) >= n:
            return congeladas

    todas = db.first_user_messages(limit=max(n * 4, 100))
    vistas = set(congeladas)
    # Pega do FIM da lista: a destilação consome do começo, então o held-out
    # cai preferencialmente nas mensagens que sobrariam de treino de qualquer jeito.
    novas = [m for m in reversed(todas) if m not in vistas]
    total = congeladas + novas[: max(0, n - len(congeladas))]
    if len(total) < min_messages:
        raise ValueError(
            f"poucas mensagens reais pra congelar o held-out de título "
            f"({len(total)} < {min_messages}) — junte mais conversas antes de medir")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(total, indent=2, ensure_ascii=False), encoding="utf-8")
    return total


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m src.nanollm.title_eval [--ckpt …]` — imprime o
    gate_accept do checkpoint no conjunto held-out congelado."""
    import argparse

    p = argparse.ArgumentParser(description="Taxa de aceitação do título (E6)")
    p.add_argument("--ckpt", default=None, help="padrão: NANO_CKPT")
    p.add_argument("--messages", default=DEFAULT_TITLE_MESSAGES)
    p.add_argument("--n", type=int, default=30)
    args = p.parse_args(argv)

    import os

    from src.storage import DatabaseManager

    ckpt = args.ckpt or os.getenv("NANO_CKPT", "data/nanollm/ckpt_v1")
    try:
        msgs = freeze_title_messages(DatabaseManager(), args.messages, n=args.n)
    except ValueError as e:
        print(f"pulado: {e}")
        return 1
    res = title_gate_accept(ckpt, msgs)
    if res.get("status") != "ok":
        print(f"pulado: {res.get('reason')}")
        return 1
    print(f"gate_accept de {ckpt}: {res['accept_rate']}% "
          f"({res['aceitos']}/{res['n']} mensagens)")
    for r in res["rounds"][:5]:
        print(f"  [{'✓' if r['ok'] else '✕'}] {r['title']!r}")
    return 0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # console cp1252 do Windows
    raise SystemExit(main())
