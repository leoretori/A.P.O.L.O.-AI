"""Briefing diário (M4, Épico 4.1): o A.P.O.L.O. te aborda de manhã com um
resumo falável. Testa a composição do texto e os dados estruturados."""
from datetime import datetime

from src.briefing import (
    _greeting,
    _join_natural,
    _plural,
    build_briefing,
    relevant_learned,
)


class FakeDB:
    def __init__(self, learned=None, schedules=None, unread=0, reminders=None):
        self._learned = learned if learned is not None else []
        self._schedules = schedules if schedules is not None else []
        self._unread = unread
        self._reminders = reminders if reminders is not None else []
    def get_learned_since(self, hours): return self._learned
    def list_schedules(self): return self._schedules
    def unread_count(self): return self._unread
    def list_reminders(self, pending_only=True, limit=5): return self._reminders


class FakeEpisodic:
    def __init__(self, eps=None): self._eps = eps or []
    def recent(self, n): return self._eps[:n]


class FakeProfile:
    """Perfil com by_category — só o que o briefing consome (M17.1)."""
    def __init__(self, groups=None): self._g = groups or {}
    def by_category(self): return self._g


def test_greeting_por_periodo():
    assert _greeting(datetime(2026, 7, 6, 8)) == "Bom dia"
    assert _greeting(datetime(2026, 7, 6, 14)) == "Boa tarde"
    assert _greeting(datetime(2026, 7, 6, 21)) == "Boa noite"


def test_join_natural():
    assert _join_natural(["a"]) == "a"
    assert _join_natural(["a", "b"]) == "a e b"
    assert _join_natural(["a", "b", "c"]) == "a, b e c"


def test_plural():
    assert _plural(1, "tópico", "tópicos") == "1 tópico"
    assert _plural(3, "tópico", "tópicos") == "3 tópicos"


def test_briefing_completo():
    db = FakeDB(
        learned=[{"topic": "asyncio python"}, {"topic": "fastapi streaming"}],
        schedules=[{"topic": "Rust", "time_of_day": "08:00", "enabled": True}],
        unread=2,
    )
    ep = FakeEpisodic([{"title": "fechamos o M3", "occurred_at": "2026-07-05T20:00:00"}])
    b = build_briefing(db=db, episodic=ep, hours=12, now=datetime(2026, 7, 6, 8))
    assert b["greeting"] == "Bom dia"
    assert b["learned_count"] == 2
    assert b["unread_notifications"] == 2
    assert b["schedules_today"][0]["topic"] == "Rust"
    assert b["episodes"][0]["title"] == "fechamos o M3"
    # texto falável tem as peças principais
    t = b["text"]
    assert t.startswith("Bom dia!")
    assert "2 tópicos novos" in t
    assert "fechamos o M3" in t
    assert "Rust" in t
    assert "2 notificações não lidas" in t


# ─────────────────────────── M17.1: priorização pessoal ───────────────────────
def test_relevant_learned_casa_com_projeto():
    learned = [{"topic": "asyncio event loop em python"},
               {"topic": "receitas de bolo de cenoura"}]
    focus = [{"text": "projeto Apolo AI com python e asyncio", "category": "project"}]
    rel = relevant_learned(learned, focus)
    assert len(rel) == 1                          # só o tópico relacionado
    assert "asyncio" in rel[0]["topic"]
    assert rel[0]["focus_category"] == "project"
    assert "asyncio" in rel[0]["shared"] or "python" in rel[0]["shared"]


def test_relevant_learned_sem_foco_ou_sem_aprendizado():
    assert relevant_learned([], [{"text": "x", "category": "goal"}]) == []
    assert relevant_learned([{"topic": "algo"}], []) == []


def test_relevant_learned_dedup_por_foco():
    # 2 tópicos casam o MESMO projeto → só 1 destaque (o mais forte)
    learned = [{"topic": "python asyncio avancado"}, {"topic": "python typing e asyncio"}]
    focus = [{"text": "projeto em python asyncio", "category": "project"}]
    rel = relevant_learned(learned, focus)
    assert len(rel) == 1


def test_briefing_prioriza_metas_e_projetos():
    db = FakeDB(learned=[{"topic": "asyncio streaming em python"},
                         {"topic": "jardinagem urbana"}])
    prof = FakeProfile({"project": [{"fact": "Apolo AI em python asyncio", "category": "project"}]})
    b = build_briefing(db=db, episodic=FakeEpisodic(), profile=prof,
                       now=datetime(2026, 7, 6, 8))
    assert b["relevant_to_you"], "deveria destacar o que toca o projeto"
    assert b["relevant_to_you"][0]["focus_category"] == "project"
    assert "seu projeto" in b["text"] and "Apolo AI" in b["text"]


def test_briefing_sem_profile_igual_a_antes():
    """Sem profile, o briefing é o de sempre (retrocompatível)."""
    db = FakeDB(learned=[{"topic": "asyncio"}])
    b = build_briefing(db=db, episodic=FakeEpisodic(), now=datetime(2026, 7, 6, 8))
    assert b["relevant_to_you"] == []
    assert "conecta com" not in b["text"]


def test_briefing_dia_vazio():
    b = build_briefing(db=FakeDB(), episodic=FakeEpisodic(), now=datetime(2026, 7, 6, 9))
    assert b["learned_count"] == 0
    assert "Nada de novo por aqui" in b["text"]


def test_briefing_schedule_desativado_nao_entra():
    db = FakeDB(schedules=[{"topic": "off", "time_of_day": "07:00", "enabled": False}])
    b = build_briefing(db=db, now=datetime(2026, 7, 6, 9))
    assert b["schedules_today"] == []


def test_briefing_sem_db_nao_quebra():
    b = build_briefing(db=None, episodic=None, now=datetime(2026, 7, 6, 9))
    assert b["learned_count"] == 0 and b["text"].startswith("Bom dia!")


def test_briefing_singular_um_topico():
    db = FakeDB(learned=[{"topic": "redis"}])
    b = build_briefing(db=db, now=datetime(2026, 7, 6, 9))
    assert "1 tópico novo" in b["text"]


def test_briefing_inclui_lembretes():
    db = FakeDB(reminders=[{"text": "revisar o PR", "due_at": None},
                           {"text": "ligar pro médico", "due_at": None}])
    b = build_briefing(db=db, now=datetime(2026, 7, 6, 9))
    assert [r["text"] for r in b["reminders"]] == ["revisar o PR", "ligar pro médico"]
    assert "Você me pediu para lembrar: revisar o PR e ligar pro médico." in b["text"]
