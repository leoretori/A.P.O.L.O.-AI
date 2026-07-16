"""Placar histórico append-only genérico (JSONL) — extraído depois da 3ª cópia
quase idêntica (`blind_eval.append_history`/P1.4, `quality_sampler`/P2.5,
`recall_calibration`/P2.6). Cada linha é 1 rodada; nunca reescreve o passado."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def append_entry(path: str | Path, fields: dict) -> None:
    """Acrescenta 1 linha com timestamp UTC automático + os campos dados."""
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **fields}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_entries(path: str | Path, limit: int = 50) -> list[dict]:
    """Mais recente por último (ordem de gravação) — as últimas `limit` linhas."""
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines[-limit:]]
