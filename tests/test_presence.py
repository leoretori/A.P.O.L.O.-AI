"""Presença ambiente (M23, Épicos 23.1/23.3) — avisa ANTES do compromisso
chegar (23.1) e se comporta conforme o momento do dia (23.3). Núcleo
determinístico, sem LLM."""
from datetime import datetime, timedelta

from src.presence import (
    PresenceMonitor,
    current_mode,
    format_heads_up,
    heads_up_due,
    should_notify,
)


def _ev(summary="Reunião", minutes_from_now=10, now=None, location=""):
    now = now or datetime(2026, 7, 15, 14, 0)
    return {"summary": summary, "location": location,
            "start": now + timedelta(minutes=minutes_from_now), "all_day": False}


# ── heads_up_due (pura) ──────────────────────────────────────────
def test_evento_dentro_da_janela_e_devido():
    now = datetime(2026, 7, 15, 14, 0)
    ev = _ev(minutes_from_now=10, now=now)
    assert heads_up_due([ev], now, set()) == [ev]


def test_evento_fora_da_janela_nao_e_devido():
    now = datetime(2026, 7, 15, 14, 0)
    longe = _ev(minutes_from_now=60, now=now)      # muito no futuro
    ja_passou = _ev(minutes_from_now=-5, now=now)   # já começou
    assert heads_up_due([longe, ja_passou], now, set()) == []


def test_evento_no_limite_da_janela_e_devido():
    now = datetime(2026, 7, 15, 14, 0)
    no_limite = _ev(minutes_from_now=15, now=now)
    assert heads_up_due([no_limite], now, set(), lookahead_min=15) == [no_limite]


def test_evento_ja_avisado_nao_repete():
    now = datetime(2026, 7, 15, 14, 0)
    ev = _ev(minutes_from_now=5, now=now)
    from src.presence import _event_key
    assert heads_up_due([ev], now, {_event_key(ev)}) == []


def test_evento_sem_start_e_ignorado():
    ev = {"summary": "quebrado", "start": None, "location": ""}
    assert heads_up_due([ev], datetime.now(), set()) == []


def test_heads_up_due_nao_muta_o_conjunto_recebido():
    now = datetime(2026, 7, 15, 14, 0)
    ev = _ev(minutes_from_now=5, now=now)
    already = set()
    heads_up_due([ev], now, already)
    assert already == set()  # função pura — quem chama decide quando marcar


# ── format_heads_up ──────────────────────────────────────────────
def test_format_com_local():
    ev = _ev(summary="Dentista", minutes_from_now=10,
             now=datetime(2026, 7, 15, 14, 0), location="Clínica Sul")
    texto = format_heads_up(ev)
    assert "Dentista" in texto and "Clínica Sul" in texto and "14:10" in texto


def test_format_sem_local():
    ev = _ev(summary="Call", minutes_from_now=5, now=datetime(2026, 7, 15, 9, 0))
    texto = format_heads_up(ev)
    assert "Call" in texto and " em " not in texto


def test_format_sem_titulo():
    ev = _ev(summary="", minutes_from_now=5, now=datetime(2026, 7, 15, 9, 0))
    assert "(sem título)" in format_heads_up(ev)


# ── PresenceMonitor (com estado, entre ticks) ────────────────────
def test_monitor_avisa_uma_vez_so():
    now = datetime(2026, 7, 15, 14, 0)
    ev = _ev(minutes_from_now=5, now=now)
    mon = PresenceMonitor()
    assert mon.check([ev], now) == [ev]         # 1º tick: avisa
    assert mon.check([ev], now) == []            # 2º tick (mesmo evento): não repete


def test_monitor_avisa_evento_diferente_normalmente():
    now = datetime(2026, 7, 15, 14, 0)
    ev1 = _ev(summary="A", minutes_from_now=5, now=now)
    ev2 = _ev(summary="B", minutes_from_now=8, now=now)
    mon = PresenceMonitor()
    assert mon.check([ev1], now) == [ev1]
    assert mon.check([ev2], now) == [ev2]


def test_monitor_poda_entradas_com_mais_de_1_dia():
    now = datetime(2026, 7, 15, 14, 0)
    ev = _ev(minutes_from_now=5, now=now)
    mon = PresenceMonitor()
    mon.check([ev], now)
    assert len(mon._notified) == 1
    depois = now + timedelta(days=2)
    mon._prune(depois)
    assert len(mon._notified) == 0


# ── current_mode / should_notify (M23.3) ─────────────────────────
def test_madrugada_e_descanso():
    assert current_mode(datetime(2026, 7, 15, 2, 0)) == "descanso"
    assert current_mode(datetime(2026, 7, 15, 23, 30)) == "descanso"


def test_janela_de_foco_configuravel():
    assert current_mode(datetime(2026, 7, 15, 10, 0)) == "foco"       # dentro (9-12 padrão)
    assert current_mode(datetime(2026, 7, 15, 8, 30)) == "trabalho"    # antes do foco


def test_resto_do_dia_e_trabalho():
    assert current_mode(datetime(2026, 7, 15, 15, 0)) == "trabalho"
    assert current_mode(datetime(2026, 7, 15, 20, 0)) == "trabalho"


def test_limites_das_janelas_sao_inclusivos_no_inicio():
    assert current_mode(datetime(2026, 7, 15, 23, 0)) == "descanso"   # rest_start exato
    assert current_mode(datetime(2026, 7, 15, 7, 0)) == "trabalho"     # rest_end exato (já saiu)
    assert current_mode(datetime(2026, 7, 15, 9, 0)) == "foco"         # focus_start exato
    assert current_mode(datetime(2026, 7, 15, 12, 0)) == "trabalho"    # focus_end exato (já saiu)


def test_janelas_customizadas_via_kwargs():
    # foco à tarde, descanso mais cedo — configurável sem mexer no default
    m = current_mode(datetime(2026, 7, 15, 14, 30),
                     rest_start=21, rest_end=6, focus_start=13, focus_end=17)
    assert m == "foco"


def test_should_notify_silencia_baixa_prioridade_no_descanso():
    assert should_notify("study", "descanso") is False
    assert should_notify("info", "descanso") is False


def test_should_notify_nao_silencia_o_sensivel_a_tempo_no_descanso():
    assert should_notify("reminder", "descanso") is True
    assert should_notify("briefing", "descanso") is True


def test_should_notify_fora_do_descanso_sempre_libera():
    assert should_notify("study", "foco") is True
    assert should_notify("study", "trabalho") is True
