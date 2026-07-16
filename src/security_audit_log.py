"""Registro histórico de auditorias de segurança (P4.2).

Antes, a auditoria de 15/07 (4 vulnerabilidades reais achadas e corrigidas —
CSRF em captura de tela/câmera, SSRF via redirect, bypass de undo, vazamento de
conteúdo de arquivo) só ficou registrada em commit messages, sem um lugar único
pra ver "o que já foi auditado e quando" sem garimpar `git log`. Mesmo padrão
JSONL append-only do resto do projeto (`src.jsonl_history` — P1.4/P2.5/P2.6):
nunca reescreve o passado, cada linha é 1 auditoria completa.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PATH = "data/security_audit_history.jsonl"


def log_audit(path: str | Path, *, date: str, trigger: str,
              findings: list[dict], notes: str = "") -> dict:
    """Registra 1 auditoria completa. `findings` é uma lista de
    `{"category": ..., "severity": "high"|"medium"|"low", "file": ...,
    "summary": ..., "status": "fixed"|"open"|"wontfix"}`. `trigger`:
    "manual" (Leo/Claude decidiu rodar) ou "pre-merge-large" (critério
    objetivo do P4.1 bateu antes de um merge grande)."""
    from src.jsonl_history import append_entry

    entry = {
        "date": date, "trigger": trigger, "findings": findings,
        "total": len(findings),
        "fixed": sum(1 for f in findings if f.get("status") == "fixed"),
        "notes": notes,
    }
    append_entry(path, entry)
    return entry


def read_audit_history(path: str | Path, limit: int = 20) -> list[dict]:
    """Lê o histórico de auditorias, mais recente por último."""
    from src.jsonl_history import read_entries

    return read_entries(path, limit)
