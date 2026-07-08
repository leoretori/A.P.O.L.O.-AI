"""Automação de rotinas (M10, Épico 10.2).

Uma ROTINA é uma tarefa recorrente que o A.P.O.L.O. executa sozinho no horário
combinado — ex.: "toda sexta, gere o resumo da semana e salve num arquivo". Ela
casa o agendador (que já existe) com as AÇÕES reversíveis do 10.1: cada execução
passa por `apply_action`, então entra no ledger de undo + auditoria e continua
100% reversível (é assim que uma rotina autônoma respeita o espírito do M10 —
você aprova a rotina uma vez, e cada resultado fica auditável e desfazível).

Núcleo DETERMINÍSTICO e testável: `is_due` decide o disparo a partir de now +
last_run (sem relógio escondido), e os "builders" montam a ação a aplicar a partir
de dados do banco (sem LLM — reusa os digests que já temos).
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("apolo.routines")

FREQS = ("daily", "weekly", "monthly")
_WEEKDAYS_PT = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def is_due(routine: dict, now: datetime, last_run=None) -> bool:
    """A rotina deve disparar AGORA? Determinístico: depende só de now e last_run.
    Dispara quando chegou/passou o horário do dia E ainda não rodou neste período
    (dia/semana/mês). Perdeu a janela (app fora no dia) → não dispara retroativo."""
    if not routine.get("enabled", True):
        return False
    freq = routine.get("freq", "daily")
    hhmm = now.strftime("%H:%M")
    if (routine.get("time_of_day") or "00:00") > hhmm:
        return False                                # ainda não chegou a hora hoje
    lr = _parse_dt(last_run if last_run is not None else routine.get("last_run"))
    ran_today = bool(lr and lr.date() == now.date())
    if ran_today:
        return False                                # já rodou hoje (1× por dia máx.)
    if freq == "daily":
        return True
    if freq == "weekly":
        return now.weekday() == int(routine.get("weekday", 0))
    if freq == "monthly":
        return now.day == int(routine.get("day_of_month", 1))
    return False


def due_routines(routines: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    return [r for r in routines if is_due(r, now)]


def describe_schedule(routine: dict) -> str:
    """Frase humana do agendamento ('toda sexta às 18:00')."""
    freq = routine.get("freq", "daily")
    t = routine.get("time_of_day", "00:00")
    if freq == "weekly":
        wd = _WEEKDAYS_PT[int(routine.get("weekday", 0)) % 7]
        return f"toda {wd} às {t}"
    if freq == "monthly":
        return f"todo dia {int(routine.get('day_of_month', 1))} às {t}"
    return f"todo dia às {t}"


# ── Builders de conteúdo (determinísticos, sem LLM) ─────────────

def build_weekly_digest_md(db, now: datetime | None = None, days: int = 7) -> str:
    """Markdown do que foi aprendido/feito na última semana — reusa os dados que
    já temos (get_learned_since + setores + episódios + lembretes)."""
    now = now or datetime.now()
    from src.topics import classify_sector, SECTOR_LABELS

    learned = []
    try:
        learned = db.get_learned_since(days * 24) if db else []
    except Exception as e:
        logger.debug(f"weekly digest learned: {e}")

    by_sector: dict[str, list[str]] = {}
    for it in learned:
        sec = classify_sector(it.get("topic", ""))
        by_sector.setdefault(sec, []).append(it.get("topic", ""))

    lines = [f"# Resumo da semana — {now.strftime('%d/%m/%Y')}", ""]
    lines.append(f"Gerado automaticamente pelo A.P.O.L.O. · janela: últimos {days} dias.")
    lines.append("")
    lines.append(f"## 📚 O que aprendi ({len(learned)} tópicos)")
    if by_sector:
        for sec, topics in sorted(by_sector.items(), key=lambda kv: -len(kv[1])):
            label = SECTOR_LABELS.get(sec, sec)
            lines.append(f"\n### {label} ({len(topics)})")
            for t in topics[:15]:
                lines.append(f"- {t}")
            if len(topics) > 15:
                lines.append(f"- …e mais {len(topics) - 15}")
    else:
        lines.append("\n_Nada estudado nesta janela._")

    # Episódios da semana (o que fizemos), se houver
    episodes = []
    try:
        episodes = db.recent_episodes(5) if db and hasattr(db, "recent_episodes") else []
    except Exception:
        episodes = []
    if episodes:
        lines.append("\n## 🗓️ O que fizemos")
        for e in episodes:
            lines.append(f"- {e.get('title', '')}")

    lines.append("")
    return "\n".join(lines)


def _weekly_digest(routine: dict, db, now: datetime) -> dict:
    md = build_weekly_digest_md(db, now)
    cfg = routine.get("config") or {}
    path = cfg.get("path") or "resumo-semana.md"
    return {"action_kind": "files.write", "args": {"path": path, "content": md},
            "description": f"Resumo da semana → {path}"}


# Registro de tipos de rotina disponíveis. Cada builder: (routine, db, now) ->
# {action_kind, args, description}. Novos tipos entram aqui.
_BUILDERS = {
    "weekly_digest": _weekly_digest,
}

KINDS = {
    "weekly_digest": "Resumo da semana salvo em arquivo (o que aprendi + fizemos)",
}


def run_routine(routine: dict, db, now: datetime | None = None) -> dict:
    """Executa uma rotina: monta a ação via builder e a APLICA pelo motor do 10.1
    (que audita e grava o undo). Devolve o resultado da ação + o undo_id."""
    now = now or datetime.now()
    builder = _BUILDERS.get(routine.get("kind"))
    if not builder:
        return {"ok": False, "error": f"tipo de rotina desconhecido: {routine.get('kind')}"}
    try:
        spec = builder(routine, db, now)
    except Exception as e:
        return {"ok": False, "error": f"falha ao montar a rotina: {e}"}
    from src.actions import apply_action
    res = apply_action(spec["action_kind"], spec.get("args"), db)
    return {**res, "routine": routine.get("name"), "description": spec["description"]}
