"""Automação de rotinas (M10, Épico 10.2).

Trava o agendamento DETERMINÍSTICO (`is_due`: dispara na hora certa, uma vez por
período, sem repetir), o digest semanal (markdown a partir do banco, sem LLM) e o
`run_routine` — que executa via o motor de ações do 10.1, então grava no ledger de
undo (reversível) e escreve de verdade numa pasta autorizada.
"""
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from src import routines as R
from src.tools import files_write  # noqa: F401  registra a ação files.write


# ── is_due (determinístico) ─────────────────────────────────────
def _routine(**kw):
    base = {"enabled": True, "freq": "weekly", "weekday": 4,
            "day_of_month": 1, "time_of_day": "18:00", "last_run": None}
    return {**base, **kw}


def test_weekly_dispara_na_sexta_apos_o_horario():
    sexta_18h = datetime(2026, 7, 10, 18, 5)      # 2026-07-10 é sexta
    assert sexta_18h.weekday() == 4
    assert R.is_due(_routine(), sexta_18h) is True


def test_weekly_nao_dispara_antes_do_horario():
    sexta_manha = datetime(2026, 7, 10, 9, 0)
    assert R.is_due(_routine(), sexta_manha) is False


def test_weekly_nao_dispara_em_outro_dia():
    quinta_18h = datetime(2026, 7, 9, 18, 5)      # quinta
    assert R.is_due(_routine(), quinta_18h) is False


def test_nao_repete_no_mesmo_dia():
    sexta = datetime(2026, 7, 10, 18, 30)
    r = _routine(last_run="2026-07-10T18:05:00")
    assert R.is_due(r, sexta) is False            # já rodou hoje


def test_dispara_de_novo_na_semana_seguinte():
    prox_sexta = datetime(2026, 7, 17, 18, 5)
    r = _routine(last_run="2026-07-10T18:05:00")
    assert R.is_due(r, prox_sexta) is True


def test_daily_dispara_todo_dia_apos_horario():
    r = _routine(freq="daily", time_of_day="08:00")
    assert R.is_due(r, datetime(2026, 7, 8, 9, 0)) is True


def test_desabilitada_nunca_dispara():
    assert R.is_due(_routine(enabled=False), datetime(2026, 7, 10, 18, 5)) is False


def test_describe_schedule_humano():
    assert R.describe_schedule(_routine()) == "toda sexta às 18:00"
    assert R.describe_schedule(_routine(freq="daily", time_of_day="07:30")) == "todo dia às 07:30"


# ── digest semanal (sem LLM) ────────────────────────────────────
class _DigestDB:
    def get_learned_since(self, hours):
        return [{"topic": "Python asyncio"}, {"topic": "Docker compose"},
                {"topic": "FastAPI depends"}]

    def recent_episodes(self, n):
        return [{"title": "fechamos o M10 10.1"}]


def test_build_weekly_digest_md():
    md = R.build_weekly_digest_md(_DigestDB(), datetime(2026, 7, 10))
    assert "# Resumo da semana — 10/07/2026" in md
    assert "O que aprendi (3 tópicos)" in md
    assert "Python asyncio" in md
    assert "fechamos o M10 10.1" in md            # episódios entram


# ── run_routine → aplica pela ação (reversível) ─────────────────
class _RunDB:
    """DB fake com o mínimo p/ o builder + o portão do motor de ações."""
    def __init__(self, note):
        self.note, self._undo, self._seq = note, {}, 0

    def get_learned_since(self, hours): return [{"topic": "Kafka streams"}]
    def recent_episodes(self, n): return []
    def is_permission_granted(self, scope): return True
    def permission_note(self, scope): return self.note
    def log_tool(self, *a): pass

    def save_undo(self, kind, desc, data):
        self._seq += 1
        self._undo[self._seq] = {"kind": kind, "undo_data": data}
        return self._seq


def test_run_routine_escreve_e_fica_reversivel():
    d = Path(tempfile.mkdtemp())
    alvo = d / "resumo.md"
    db = _RunDB(note=str(d))
    routine = {"name": "Resumo", "kind": "weekly_digest", "config": {"path": str(alvo)}}

    res = R.run_routine(routine, db, datetime(2026, 7, 10))
    assert res["ok"] and res["undo_id"] == 1       # entrou no ledger (reversível)
    assert alvo.read_text(encoding="utf-8").startswith("# Resumo da semana")
    assert "Kafka streams" in alvo.read_text(encoding="utf-8")


def test_run_routine_tipo_desconhecido():
    assert R.run_routine({"name": "x", "kind": "nao_existe"}, None)["ok"] is False
