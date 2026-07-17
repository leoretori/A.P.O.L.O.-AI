"""Histórico de experimentos de fine-tune do Apolo-Nano (item 3 do
PLANO_CORPUS_DIVERSO.md).

Antes, cada tentativa (título 4.2, resposta `ckpt_answer_v1`, gate binário, o
`medium` do M26) vivia só num checkpoint solto e numa nota de commit — sem um
lugar único pra ver "o que já foi tentado e o resultado" sem garimpar `git
log`. Mesmo padrão JSONL append-only do resto do projeto (`src.jsonl_history`)
usado em auditoria de segurança/qualidade/recall-gate: nunca reescreve o
passado, cada linha é 1 experimento completo.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_PATH = "data/nano/experiment_history.jsonl"


def log_experiment(
    path: str | Path,
    *,
    name: str,
    base_ckpt: str,
    dataset: str,
    hyperparams: dict,
    result: dict,
    notes: str = "",
) -> dict:
    """Registra 1 tentativa de fine-tune. `hyperparams` é livre (ex.: `lr`,
    `steps`, `patience`); `result` é livre (ex.: `win_rate`, `accuracy`,
    `promoted`) — cada tarefa (título/resposta/binário) mede coisas diferentes,
    então não força um schema único."""
    from src.jsonl_history import append_entry

    entry = {
        "name": name, "base_ckpt": base_ckpt, "dataset": dataset,
        "hyperparams": hyperparams, "result": result, "notes": notes,
    }
    append_entry(path, entry)
    return entry


def read_experiment_history(path: str | Path, limit: int = 50) -> list[dict]:
    """Lê o histórico de experimentos, mais recente por último."""
    from src.jsonl_history import read_entries

    return read_entries(path, limit)
