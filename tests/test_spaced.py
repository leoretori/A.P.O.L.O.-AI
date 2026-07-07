"""Repetição espaçada SM-2 (M8, Épico 8.1). Núcleo determinístico."""
from datetime import datetime

from src import spaced as S


def test_intervalos_crescem_ao_lembrar():
    st = S.initial_state()
    st = S.review(st, 5); assert st["interval"] == 1 and st["reps"] == 1
    st = S.review(st, 5); assert st["interval"] == 6 and st["reps"] == 2
    st = S.review(st, 5); assert st["interval"] > 6 and st["reps"] == 3   # 6*ease
    prev = st["interval"]
    st = S.review(st, 4); assert st["interval"] > prev                    # continua crescendo


def test_esquecer_reseta_e_conta_lapso():
    st = S.review(S.review(S.initial_state(), 5), 5)   # reps=2, interval=6
    st = S.review(st, 1)                                # esqueceu
    assert st["interval"] == 1 and st["reps"] == 0 and st["lapses"] == 1


def test_ease_nunca_abaixo_do_minimo():
    st = S.initial_state()
    for _ in range(10):
        st = S.review(st, 3)               # notas apertadas puxam o ease pra baixo
    assert st["ease"] >= S.MIN_EASE


def test_next_due_usa_intervalo():
    now = datetime(2026, 7, 7, 12, 0)
    st = {"interval": 6}
    assert (S.next_due(st, now) - now).days == 6
    # intervalo 0 vira pelo menos 1 dia
    assert (S.next_due({"interval": 0}, now) - now).days == 1


def test_quality_from_recall():
    assert S.quality_from_recall(None, has_hit=False) == 2      # esqueceu
    assert S.quality_from_recall(0.9, has_hit=True) == 5        # lembrou muito bem
    assert S.quality_from_recall(0.6, has_hit=True) == 4
    assert S.quality_from_recall(0.4, has_hit=True) == 3
    assert S.quality_from_recall(0.1, has_hit=True) == 2        # acerto fraco


def test_pass_sobe_intervalo_fail_desce():
    # lembrar (q>=3) faz o intervalo crescer; esquecer (q<3) reseta p/ 1
    lembrou = S.review({"ease": 2.5, "interval": 6, "reps": 2, "lapses": 0}, 5)
    assert lembrou["interval"] > 6
    esqueceu = S.review({"ease": 2.5, "interval": 6, "reps": 2, "lapses": 0}, 2)
    assert esqueceu["interval"] == 1
