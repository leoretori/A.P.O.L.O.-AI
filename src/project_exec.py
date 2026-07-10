"""Execução supervisionada de projetos (M19.1 — "do propor ao fazer").

Os projetos autodirigidos do M12 (src/projects.py) só PROPUNHAM passos; o Leo
executava tudo na mão. Aqui os passos ganham um EXECUTOR: operações reais que o
A.P.O.L.O. roda sozinho, sempre no contrato de dois passos do M10 —

    preview  → mostra EXATAMENTE o que rodar aquele passo faria, SEM efeito
    run      → aplica de fato e RE-MEDE a métrica que motivou o projeto

Cada operação embrulha uma função que JÁ existe e é testada (medir qualidade de
síntese, contar/limpar duplicatas...), então o núcleo aqui é só o registro +
roteamento — determinístico e testável. Passos sem operação registrada seguem
manuais (checklist), como antes: nada roda escondido.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ExecContext:
    """Os singletons de runtime que as operações usam (injetados pelo router)."""
    db: object | None = None
    rag: object | None = None
    learner: object | None = None


@dataclass
class StepOp:
    key: str
    label: str
    mutates: bool                          # muda dados? (mutação exige preview antes)
    preview: Callable[["ExecContext"], dict]   # SEM efeito colateral
    run: Callable[["ExecContext"], dict]       # aplica; devolve {result, measure?}


_REGISTRY: dict[str, StepOp] = {}


def register(op: StepOp) -> None:
    _REGISTRY[op.key] = op


def get_op(key: str) -> StepOp | None:
    return _REGISTRY.get(key)


def all_ops() -> list[StepOp]:
    return list(_REGISTRY.values())


# ─────────────────────────────────────────────────────────────────────────
# Operações concretas — cada uma embrulha uma função real já existente.
# ─────────────────────────────────────────────────────────────────────────

def _pct(q: dict) -> str:
    p = q.get("pct_structured")
    return f"{p}%" if p is not None else "?"


def _measure_summary_quality_preview(ctx: ExecContext) -> dict:
    q = ctx.db.get_summary_quality()
    return {"summary": f"Medir a qualidade das sínteses (hoje {_pct(q)} estruturadas, "
                       f"{q.get('raw', 0)} cruas). Só lê, não muda nada.",
            "metric": q}


def _measure_summary_quality_run(ctx: ExecContext) -> dict:
    q = ctx.db.get_summary_quality()
    return {"result": q,
            "measure": {"pct_structured": q.get("pct_structured"), "raw": q.get("raw", 0)}}


def _measure_duplicates_preview(ctx: ExecContext) -> dict:
    n = ctx.db.count_topic_duplicates()
    return {"summary": f"Contar as duplicatas do log de tópicos (hoje {n}). Só lê.",
            "count": n}


def _measure_duplicates_run(ctx: ExecContext) -> dict:
    n = ctx.db.count_topic_duplicates()
    return {"result": {"duplicates": n}, "measure": {"duplicates": n}}


def _dedup_topics_preview(ctx: ExecContext) -> dict:
    n = ctx.db.count_topic_duplicates()
    return {"summary": f"Remover {n} tópico(s) duplicado(s) do log, mantendo o registro "
                       f"mais recente de cada.", "count": n}


def _dedup_topics_run(ctx: ExecContext) -> dict:
    removed = ctx.db.dedup_learned_topics()
    left = ctx.db.count_topic_duplicates()
    return {"result": {"removed": removed}, "measure": {"duplicates": left}}


def _dedup_index_preview(ctx: ExecContext) -> dict:
    n = ctx.rag.dedup_exact(dry_run=True)          # dry_run: conta sem apagar
    return {"summary": f"Remover {n} documento(s) de conteúdo idêntico do índice de "
                       f"recall, mantendo um de cada.", "count": n}


def _dedup_index_run(ctx: ExecContext) -> dict:
    removed = ctx.rag.dedup_exact(dry_run=False)
    return {"result": {"removed": removed}, "measure": {"removed": removed}}


register(StepOp("measure_summary_quality", "Medir a qualidade das sínteses", False,
                _measure_summary_quality_preview, _measure_summary_quality_run))
register(StepOp("measure_duplicates", "Contar duplicatas", False,
                _measure_duplicates_preview, _measure_duplicates_run))
register(StepOp("dedup_topics", "Limpar duplicatas do log de tópicos", True,
                _dedup_topics_preview, _dedup_topics_run))
register(StepOp("dedup_index", "Limpar documentos idênticos do índice", True,
                _dedup_index_preview, _dedup_index_run))


# ─────────────────────────────────────────────────────────────────────────
# Plano executável por tipo de projeto — quais passos o Apolo roda sozinho.
# Tipos ausentes ⇒ plano vazio (projeto segue 100% manual, como antes).
# ─────────────────────────────────────────────────────────────────────────
_PLANS: dict[str, list[str]] = {
    "summary_quality": ["measure_summary_quality"],
    "dedup": ["measure_duplicates", "dedup_topics", "dedup_index"],
}


def plan_for(project: dict) -> list[dict]:
    """Passos executáveis do projeto (na ordem), anotados. Determinístico."""
    kind = (project or {}).get("kind")
    out: list[dict] = []
    for key in _PLANS.get(kind, []):
        op = get_op(key)
        if op:
            out.append({"key": op.key, "label": op.label, "mutates": op.mutates,
                        "executable": True})
    return out


def preview_step(key: str, ctx: ExecContext) -> dict:
    """Fase 1: o que rodar este passo faria — sem efeito colateral."""
    op = get_op(key)
    if not op:
        return {"ok": False, "error": f"passo executável desconhecido: {key}"}
    try:
        return {"ok": True, "key": key, "label": op.label, "mutates": op.mutates,
                "preview": op.preview(ctx)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def run_step(key: str, ctx: ExecContext) -> dict:
    """Fase 2: aplica de fato e devolve o resultado + a re-medição."""
    op = get_op(key)
    if not op:
        return {"ok": False, "error": f"passo executável desconhecido: {key}"}
    try:
        out = op.run(ctx)
        return {"ok": True, "key": key, "label": op.label, "mutated": op.mutates, **out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


# ─────────────────────────────────────────────────────────────────────────
# 19.2 — Plano multi-passo VERIFICÁVEL com checkpoints.
# O Apolo roda a sequência sozinho: executa os passos SEGUROS (medições) e PARA
# para confirmar nos pontos sensíveis (mutações). Idempotente e retomável SEM
# store novo: uma mutação já aplicada re-mede 0 pendências → é pulada, e o plano
# segue até o próximo checkpoint.
# ─────────────────────────────────────────────────────────────────────────

def _is_noop(preview: dict) -> bool:
    """A mutação não tem o que fazer? (preview reporta contagem zero.)"""
    return preview.get("count") == 0


def run_plan(project: dict, ctx: ExecContext, *, confirm: str | None = None) -> dict:
    """Roda o plano do projeto em ordem, parando no 1º passo sensível não
    confirmado (checkpoint). `confirm` = a chave do passo que o Leo autorizou
    AGORA. Devolve `status` ∈ {'done','needs_confirmation','empty'} + o que rodou
    e o progresso, para o front reportar e retomar."""
    steps = plan_for(project)
    if not steps:
        return {"status": "empty", "ran": [], "progress": 0, "total": 0}
    ran: list[dict] = []
    for i, s in enumerate(steps):
        key = s["key"]
        if s["mutates"]:
            pv = preview_step(key, ctx)
            preview = pv.get("preview", {}) if pv.get("ok") else {}
            if _is_noop(preview):            # nada a fazer → já resolvido, pula
                ran.append({"key": key, "label": s["label"], "ok": True,
                            "mutated": False, "skipped": True})
                continue
            if key != confirm:               # checkpoint: para e pede confirmação
                return {"status": "needs_confirmation", "checkpoint": key,
                        "label": s["label"], "preview": preview,
                        "ran": ran, "progress": round(100 * i / len(steps)),
                        "total": len(steps)}
            confirm = None                   # token consumido: vale p/ ESTA mutação
        out = run_step(key, ctx)
        ran.append({"key": key, "label": s["label"], "ok": out.get("ok"),
                    "mutated": out.get("mutated", False), "measure": out.get("measure")})
    return {"status": "done", "ran": ran, "progress": 100, "total": len(steps)}
