"""Antecipação útil (M17.3): sugere retomar metas/projetos negligenciados."""

from src.anticipation import habit_period, suggest_anticipations


class FakeProfile:
    def __init__(self, groups=None): self._g = groups or {}
    def by_category(self): return self._g


def _prof(projects=(), goals=(), habits=()):
    g = {}
    if projects:
        g["project"] = [{"fact": p, "category": "project"} for p in projects]
    if goals:
        g["goal"] = [{"fact": x, "category": "goal"} for x in goals]
    if habits:
        g["habit"] = [{"fact": h, "category": "habit"} for h in habits]
    return FakeProfile(g)


def test_habit_period():
    assert habit_period("estudo IA de manhã") == "de manhã"
    assert habit_period("treino à noite") == "à noite"
    assert habit_period("leio à tarde") == "à tarde"
    assert habit_period("gosto de café") is None


def test_sugere_foco_nao_tocado():
    prof = _prof(projects=["Apolo AI em python asyncio"])
    # atividade recente sobre OUTRA coisa → o projeto foi negligenciado
    sug = suggest_anticipations(prof, ["receita de bolo", "jardinagem"])
    assert len(sug) == 1
    assert sug[0]["focus_category"] == "project"
    assert "Apolo AI" in sug[0]["text"] and "retomar" in sug[0]["text"]


def test_nao_sugere_foco_tocado_recentemente():
    prof = _prof(projects=["Apolo AI em python asyncio"])
    # atividade recente CONECTA com o projeto → não sugere (não está esquecido)
    sug = suggest_anticipations(prof, ["asyncio avançado em python"])
    assert sug == []


def test_ancorada_no_habito():
    prof = _prof(goals=["aprender rust"], habits=["estudo de manhã"])
    sug = suggest_anticipations(prof, ["outra coisa qualquer"])
    assert sug[0]["habit_period"] == "de manhã"
    assert "de manhã" in sug[0]["text"]


def test_sem_habito_usa_generico():
    prof = _prof(goals=["aprender rust"])
    sug = suggest_anticipations(prof, ["outra coisa"])
    assert sug[0]["habit_period"] is None
    assert "reservar um tempo" in sug[0]["text"]


def test_projetos_antes_de_metas():
    prof = _prof(projects=["projeto Zeta"], goals=["meta Omega"])
    sug = suggest_anticipations(prof, ["nada relacionado"], limit=2)
    assert sug[0]["focus_category"] == "project"
    assert sug[1]["focus_category"] == "goal"


def test_respeita_limite():
    prof = _prof(goals=["meta A distinta", "meta B distinta", "meta C distinta"])
    assert len(suggest_anticipations(prof, ["zzz"], limit=2)) == 2


def test_sem_profile_ou_sem_foco():
    assert suggest_anticipations(None, ["x"]) == []
    assert suggest_anticipations(FakeProfile({}), ["x"]) == []


def test_integra_no_briefing():
    from datetime import datetime

    from src.briefing import build_briefing

    class DB:
        def get_learned_since(self, h): return [{"topic": "jardinagem urbana"}]
        def list_schedules(self): return []
        def unread_count(self): return 0
        def list_reminders(self, pending_only=True, limit=5): return []

    class Ep:
        def recent(self, n): return []

    prof = _prof(projects=["Apolo AI em python"], habits=["estudo de manhã"])
    b = build_briefing(db=DB(), episodic=Ep(), profile=prof,
                       now=datetime(2026, 7, 6, 8))
    assert b["anticipations"], "deveria sugerir retomar o projeto esquecido"
    assert "Apolo AI" in b["text"] and "retomar" in b["text"]
