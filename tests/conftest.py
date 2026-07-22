"""Fixtures compartilhadas da suíte."""
import pytest


@pytest.fixture(autouse=True)
def _ledger_de_reparo_isolado(tmp_path, monkeypatch):
    """Nenhum teste escreve no ledger REAL de tentativas de reparo (E9).

    O ledger é append-only e persiste entre execuções: sem isto, um teste que
    simula falha de reparo acumula tentativas em `data/repair_attempts.jsonl` e,
    depois de `MAX_REPAIR_TRIES` execuções da suíte, o próprio teste passa a
    falhar — o item que ele criou vira "desistido". Cada teste ganha o seu.
    """
    import src.learner as learner_mod
    monkeypatch.setattr(learner_mod, "REPAIR_LEDGER",
                        str(tmp_path / "repair_attempts.jsonl"), raising=False)
