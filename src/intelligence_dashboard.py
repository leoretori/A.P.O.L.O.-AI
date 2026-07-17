"""Painel único de saúde da inteligência (P5.2/P5.3 do PLANO_7_PILARES.md).

P5.1 (mapeamento — sem código, feito por leitura antes de construir isto):
as métricas hoje vivem espalhadas em `/api/health`, `/api/nano/coverage`,
`/api/nano/flywheel/diagnose`, `/api/nano/blind-eval/last` (arquivo separado,
`data/nano/blind_eval_last.json` — só o ÚLTIMO resultado, não o histórico),
`src/evals.py` (canário), `get_summary_quality()` (estrutural) e
`recall_calibration.py`. Achado no mapeamento: o blind-eval tinha DOIS
caminhos de registro (o arquivo único e o `blind_eval_history.jsonl` do
P1.4) — este painel usa o histórico JSONL (P1.4/P2.5/P2.6), que já é a
fonte de tendência real, não o arquivo de "último resultado" solto.

Este módulo consolida os 5 números que o próprio P5.2 pede: cobertura Nano,
ppl atual, win-rate blind-eval mais recente, qualidade do aprendizado (P2.5),
progresso de volume (P3.2) — e, junto (P5.3), uma janela de tendência lendo
os placares JSONL já existentes, não só o valor mais recente.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone


def cycle_health(
    history_paths: dict[str, str],
    *,
    stale_after_days: int = 2,
    now: datetime | None = None,
) -> dict[str, dict]:
    """Item 5.2 (`PLANO_CEREBRO_ASSUME.md`): há visibilidade agregada de
    RESULTADO dos ciclos noturnos, mas nenhuma de que um ciclo parou de
    RODAR. Cada história JSONL (P1.4/P2.5/P2.6) já grava `timestamp` em toda
    entrada (`src.jsonl_history.append_entry`) — basta olhar a última linha.

    Devolve, por nome de ciclo, `{last_run, days_since, stale}`.
    `last_run=None` (nunca rodou) conta como `stale=True`.

    Ressalva honesta: só é um sinal limpo para ciclos que registram TODA
    execução, mesmo quando pulam por falta de dado (P2.5 faz isso). O
    recall-gate (P2.6) só grava quando `status="ok"` — um "stale" dele pode
    significar tanto scheduler parado quanto poucos tópicos pra rodar; não
    dá pra distinguir só pela história, e não fingimos que dá."""
    from src.jsonl_history import read_entries

    now = now or datetime.now(timezone.utc)
    out: dict[str, dict] = {}
    for name, path in history_paths.items():
        entries = read_entries(path, 1)
        if not entries or "timestamp" not in entries[-1]:
            out[name] = {"last_run": None, "days_since": None, "stale": True}
            continue
        ts = datetime.fromisoformat(entries[-1]["timestamp"])
        days_since = (now - ts).total_seconds() / 86400
        out[name] = {
            "last_run": entries[-1]["timestamp"],
            "days_since": round(days_since, 1),
            "stale": days_since > stale_after_days,
        }
    return out


def build_snapshot(
    *,
    db=None,
    nano_engine=None,
    blind_eval_history_path: str = "data/nano/blind_eval_history.jsonl",
    quality_history_path: str = "data/learner/quality_history.jsonl",
    recall_gate_history_path: str = "data/learner/recall_gate_history.jsonl",
    trend_points: int = 10,
    cycle_stale_after_days: int = 2,
) -> dict:
    """Agrega tudo numa chamada só. Cada bloco é independente — um falhar (ex.:
    banco fora, arquivo ausente) não derruba os outros; vira `None`."""
    from src.jsonl_history import read_entries

    snapshot: dict = {
        "coverage": None, "nano_status": None, "volume": None,
        "blind_eval": None, "quality": None, "recall_gate": None,
        "cycles": None,
    }

    try:
        snapshot["cycles"] = cycle_health(
            {"quality": quality_history_path, "recall_gate": recall_gate_history_path},
            stale_after_days=cycle_stale_after_days,
        )
    except Exception:
        pass

    if db is not None:
        try:
            snapshot["coverage"] = db.nano_coverage()
        except Exception:
            pass
        try:
            diag = db.diagnose_pair_sourcing()
            min_pairs = int(os.getenv("FLYWHEEL_MIN_PAIRS", 5))
            snapshot["volume"] = {
                "min_pairs": min_pairs,
                "faltam_titulo": max(0, min_pairs - diag["com_1a_mensagem_valida"]),
                "faltam_reacoes": max(0, min_pairs - diag.get("pares_de_reacoes_up", 0)),
            }
        except Exception:
            pass

    if nano_engine is not None:
        try:
            snapshot["nano_status"] = nano_engine.info()
        except Exception:
            pass

    for key, path in (
        ("blind_eval", blind_eval_history_path),
        ("quality", quality_history_path),
        ("recall_gate", recall_gate_history_path),
    ):
        try:
            trend = read_entries(path, trend_points)
        except Exception:
            trend = []
        if trend:
            snapshot[key] = {"latest": trend[-1], "trend": trend}

    return snapshot
