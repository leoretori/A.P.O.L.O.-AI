"""Contadores do takeover progressivo do Nano (M27) — mixin do DatabaseManager.

Persiste, por tarefa estreita, quantas vezes o cérebro próprio (Nano) serviu vs.
o professor (Qwen/fallback). É a fonte da métrica-mãe do Ano 3: a % do dia
servida pelos pesos do Leo, subindo mês a mês."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.storage_models import NanoServe, _now


class NanoRoutingMixin:
    def nano_record_serve(self, task: str, served_by: str) -> None:
        """Incrementa o contador (task, served_by). `served_by` ∈ {nano, teacher}."""
        task = (task or "").strip()[:40]
        served_by = "nano" if served_by == "nano" else "teacher"
        if not task:
            return
        with Session(self.engine) as s:
            row = s.get(NanoServe, {"task": task, "served_by": served_by})
            if row:
                row.count += 1
                row.updated_at = _now()
            else:
                s.add(NanoServe(task=task, served_by=served_by, count=1))
            s.commit()

    def nano_coverage(self) -> dict:
        """% servida pelo Nano, geral e por tarefa. Base do painel de soberania.

        Retorna {overall: {nano, teacher, total, pct}, tasks: {task: {...}}}."""
        with Session(self.engine) as s:
            rows = (s.query(NanoServe.task, NanoServe.served_by,
                            func.sum(NanoServe.count))
                    .group_by(NanoServe.task, NanoServe.served_by).all())
        tasks: dict[str, dict] = {}
        tot_nano = tot_all = 0
        for task, by, cnt in rows:
            cnt = int(cnt or 0)
            t = tasks.setdefault(task, {"nano": 0, "teacher": 0})
            t[by] = cnt
            tot_all += cnt
            if by == "nano":
                tot_nano += cnt
        for t in tasks.values():
            t["total"] = t["nano"] + t["teacher"]
            t["pct"] = round(100 * t["nano"] / t["total"], 1) if t["total"] else 0.0
        overall = {"nano": tot_nano, "teacher": tot_all - tot_nano, "total": tot_all,
                   "pct": round(100 * tot_nano / tot_all, 1) if tot_all else 0.0}
        return {"overall": overall, "tasks": tasks}
