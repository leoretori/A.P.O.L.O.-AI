"""Notificações que importam (M4, Épico 4.3): prioridade por tipo + colapso de
avisos de baixa prioridade (anti-spam) + filtro 'só o que importa'."""
import pytest

from src.storage import DatabaseManager
from src.notifications import priority_for, collapses, collapsed_message


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/n.db")


# ── Política de relevância ────────────────────────────────────
def test_prioridade_por_tipo():
    assert priority_for("reminder") == 3
    assert priority_for("briefing") == 3
    assert priority_for("gap") == 2
    assert priority_for("study") == 0
    assert priority_for("desconhecido") == 1        # default


def test_apenas_study_colapsa():
    assert collapses("study") is True
    assert collapses("reminder") is False


def test_collapsed_message_limpa_prefixo():
    assert collapsed_message("study", 5, "📚 Estudei: asyncio") == \
        "📚 Estudei 5 tópicos (último: asyncio)"


# ── Colapso no banco (anti-spam) ──────────────────────────────
def test_avisos_study_colapsam_em_um(db):
    for t in ["asyncio", "fastapi", "kafka", "redis", "rust"]:
        db.add_notification(f"📚 Estudei: {t}", kind="study")
    items = db.list_notifications()
    assert len(items) == 1                           # 5 viraram 1
    n = items[0]
    assert n["count"] == 5 and n["priority"] == 0
    assert "5 tópicos" in n["message"] and "rust" in n["message"]


def test_tipos_importantes_nao_colapsam(db):
    db.add_notification("⏰ Lembrete: PR", kind="reminder")
    db.add_notification("🔍 Lacuna: docker", kind="gap")
    db.add_notification("📚 Estudei: x", kind="study")
    itens = db.list_notifications()
    assert len(itens) == 3
    prios = {n["kind"]: n["priority"] for n in itens}
    assert prios == {"reminder": 3, "gap": 2, "study": 0}


def test_filtro_min_priority_esconde_ruido(db):
    db.add_notification("⏰ Lembrete", kind="reminder")     # p3
    db.add_notification("🔍 Lacuna", kind="gap")            # p2
    for t in ("a", "b", "c"):
        db.add_notification(f"estudei {t}", kind="study")   # p0 (colapsa)
    importantes = db.list_notifications(min_priority=2)
    assert len(importantes) == 2
    assert all(n["priority"] >= 2 for n in importantes)
    assert {n["kind"] for n in importantes} == {"reminder", "gap"}


def test_study_lido_nao_colapsa_no_novo(db):
    # Um study lido não deve receber o colapso — marca lido e um novo cria linha nova.
    db.add_notification("estudei a", kind="study")
    db.mark_notifications_read()
    db.add_notification("estudei b", kind="study")
    itens = db.list_notifications()
    assert len(itens) == 2                            # o lido não foi colapsado
