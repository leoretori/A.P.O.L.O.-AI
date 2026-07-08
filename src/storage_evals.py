"""DatabaseManager — harness de avaliação (M9, Épico 9.1/9.3): histórico dos runs
canário e a TENDÊNCIA de qualidade ('estou melhorando?'). Mixin."""

import json as _json

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage_models import EvalRun


def _eval_dict(r) -> dict:
    return {"id": r.id, "ran_at": r.ran_at.isoformat() if r.ran_at else None,
            "suite": r.suite, "score": r.score, "passed": r.passed,
            "total": r.total, "hallucination_rate": r.hallucination_rate,
            "by_kind": _json.loads(r.by_kind_json or "{}"),
            "results": _json.loads(r.results_json or "[]")}


class EvalsMixin:
    def save_eval_run(self, run: dict, suite: str = "canary") -> int:
        """Persiste o placar de um run canário. `run` é a saída de evals.run_canary."""
        with Session(self.engine) as s:
            row = EvalRun(
                suite=suite,
                score=run.get("score"),
                passed=run.get("passed"),
                total=run.get("total"),
                hallucination_rate=run.get("hallucination_rate", 0.0),
                by_kind_json=_json.dumps(run.get("by_kind", {}), ensure_ascii=False),
                results_json=_json.dumps(run.get("results", []), ensure_ascii=False),
            )
            s.add(row)
            s.commit()
            return row.id

    def get_eval_history(self, limit: int = 30, suite: str = "canary") -> list[dict]:
        """Runs mais recentes primeiro (para o placar e o gráfico de tendência)."""
        with Session(self.engine) as s:
            rows = (s.query(EvalRun).filter(EvalRun.suite == suite)
                    .order_by(EvalRun.id.desc()).limit(limit).all())
            return [_eval_dict(r) for r in rows]

    def latest_eval(self, suite: str = "canary") -> dict | None:
        with Session(self.engine) as s:
            row = (s.query(EvalRun).filter(EvalRun.suite == suite)
                   .order_by(EvalRun.id.desc()).first())
            return _eval_dict(row) if row else None

    def count_eval_runs(self, suite: str = "canary") -> int:
        with Session(self.engine) as s:
            return s.query(func.count(EvalRun.id)).filter(EvalRun.suite == suite).scalar() or 0

    def eval_trend(self, window: int = 5, suite: str = "canary") -> dict:
        """Compara a janela recente de runs com a anterior — a evidência de
        'estou melhorando?'. Nota SOBE = bom; alucinação DESCE = bom."""
        with Session(self.engine) as s:
            rows = (s.query(EvalRun.score, EvalRun.hallucination_rate)
                    .filter(EvalRun.suite == suite)
                    .order_by(EvalRun.id.desc()).limit(window * 2).all())
        scores = [r[0] for r in rows if r[0] is not None]
        halls = [r[1] for r in rows if r[1] is not None]

        def _avg(xs: list) -> float | None:
            return round(sum(xs) / len(xs), 3) if xs else None

        recent_score = _avg(scores[:window])
        prev_score = _avg(scores[window:window * 2])
        recent_hall = _avg(halls[:window])
        prev_hall = _avg(halls[window:window * 2])

        def _delta(a, b):
            return round(a - b, 3) if a is not None and b is not None else None

        return {
            "runs": len(scores),
            "recent_score": recent_score, "prev_score": prev_score,
            "score_trend": _delta(recent_score, prev_score),
            "recent_hallucination": recent_hall, "prev_hallucination": prev_hall,
            # tendência de alucinação como MELHORA: queda vira número positivo
            "hallucination_trend": _delta(prev_hall, recent_hall),
        }
