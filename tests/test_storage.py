"""Testes do banco de dados — execuções e sessões persistentes."""

import pytest
from src.storage import DatabaseManager


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/test.db")


# ── Execuções ─────────────────────────────────────────────────
def test_salva_e_recupera_execucao(db):
    db.save_execution({
        "timestamp": "2024-01-01T00:00:00",
        "request": "teste",
        "result": "print('ok')",
        "status": "success",
    })
    history = db.get_history()
    assert len(history) == 1
    assert history[0]["request"] == "teste"


def test_soft_delete(db):
    exec_id = db.save_execution({
        "timestamp": "2024-01-01T00:00:00",
        "request": "deletar",
        "result": "",
        "status": "success",
    })
    assert db.soft_delete(exec_id)
    assert len(db.get_history()) == 0


def test_soft_delete_inexistente(db):
    assert not db.soft_delete(9999)


# ── Sessões ───────────────────────────────────────────────────
def test_salva_e_carrega_sessao(db):
    db.save_message("sessao-1", "user", "olá")
    db.save_message("sessao-1", "assistant", "olá! como posso ajudar?")
    msgs = db.load_session("sessao-1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_sessao_vazia(db):
    msgs = db.load_session("nao-existe")
    assert msgs == []


def test_deleta_sessao(db):
    db.save_message("sessao-del", "user", "apagar isso")
    db.delete_session("sessao-del")
    assert db.load_session("sessao-del") == []


def test_lista_sessoes(db):
    db.save_message("s1", "user", "primeira pergunta")
    db.save_message("s2", "user", "segunda pergunta")
    sessions = db.list_sessions()
    ids = [s["session_id"] for s in sessions]
    assert "s1" in ids
    assert "s2" in ids


def test_sessoes_multiplas_independentes(db):
    db.save_message("a", "user", "msg da sessão A")
    db.save_message("b", "user", "msg da sessão B")
    assert len(db.load_session("a")) == 1
    assert len(db.load_session("b")) == 1


def test_delete_session_remove_titulo(db):
    """Apagar a sessão também remove o metadado — sem títulos fantasmas."""
    db.save_message("s-meta", "user", "oi")
    db.save_session_title("s-meta", "Conversa de teste")
    db.delete_session("s-meta")
    # Não deve sobrar título órfão na listagem nem na limpeza.
    assert db.cleanup_orphan_meta() == 0
    assert all(s["session_id"] != "s-meta" for s in db.list_sessions())


def test_busca_no_historico(db):
    db.save_message("s1", "user", "como configurar o nginx como proxy reverso")
    db.save_message("s1", "assistant", "use o bloco location")
    db.save_message("s2", "user", "qual a melhor receita de pão")
    res = db.search_messages("nginx")
    assert len(res) == 1
    assert res[0]["session_id"] == "s1"
    assert "nginx" in res[0]["snippet"].lower()
    # Query curta demais não retorna nada (evita varredura inútil).
    assert db.search_messages("a") == []


def test_busca_agrupa_por_sessao(db):
    db.save_message("s1", "user", "falando de docker aqui")
    db.save_message("s1", "assistant", "docker é legal")
    res = db.search_messages("docker")
    assert len(res) == 1  # 2 acertos, 1 sessão


def test_export_all(db):
    db.save_message("s1", "user", "oi")
    db.save_session_title("s1", "Saudação")
    db.save_learned_topic("FastAPI", "http://x", "resumo", "web")
    data = db.export_all()
    assert data["counts"]["messages"] == 1
    assert data["counts"]["sessions"] == 1
    assert data["counts"]["learned_topics"] == 1
    assert data["messages"][0]["content"] == "oi"
    assert data["learned_topics"][0]["topic"] == "FastAPI"


def test_export_import_roundtrip(db, tmp_path):
    db.save_message("s1", "user", "olá mundo")
    db.save_session_title("s1", "Conversa A")
    db.save_learned_topic("Redis", "http://redis.io", "cache em memória", "web")
    dump = db.export_all()

    db2 = DatabaseManager(database_url=f"sqlite:///{tmp_path}/restore.db")
    added = db2.import_all(dump)
    assert added["messages"] == 1
    assert added["sessions"] == 1
    assert added["learned_topics"] == 1
    assert db2.load_session("s1")[0]["content"] == "olá mundo"
    assert db2.list_sessions()[0]["title"] == "Conversa A"


def test_import_idempotente(db):
    db.save_message("s1", "user", "repete?")
    db.save_learned_topic("Kafka", "http://kafka", "streaming", "web")
    dump = db.export_all()
    # Reimportar no MESMO banco não deve duplicar nada.
    added = db.import_all(dump)
    assert added["messages"] == 0
    assert added["learned_topics"] == 0
    assert len(db.load_session("s1")) == 1


def test_delete_learned_topic(db):
    db.save_learned_topic("Redis", "http://redis.io", "cache", "web")
    db.save_learned_topic("Redis", "http://redis.io", "cache v2", "web")  # re-estudo
    db.save_learned_topic("Kafka", "http://kafka", "stream", "web")
    rows = db.get_learning_history()
    redis_id = next(r["id"] for r in rows if r["topic"] == "Redis")
    info = db.delete_learned_topic(redis_id)
    assert info["topic"] == "Redis" and info["url"] == "http://redis.io"
    topics = [r["topic"] for r in db.get_learning_history()]
    assert "Redis" not in topics  # removeu todos os re-estudos
    assert "Kafka" in topics
    assert db.delete_learned_topic(999999) is None


def test_export_session_markdown(db):
    db.save_message("s1", "user", "Como faço um loop em Python?")
    db.save_message("s1", "assistant", "Use `for x in lista:`")
    db.save_session_title("s1", "Loops em Python")
    md = db.export_session_markdown("s1")
    assert md.startswith("# Loops em Python")
    assert "🧑 Você" in md and "☀️ A.P.O.L.O." in md
    assert "Como faço um loop em Python?" in md
    assert "Use `for x in lista:`" in md


def test_export_session_markdown_vazia(db):
    md = db.export_session_markdown("inexistente")
    assert md.startswith("# Conversa")


def test_notificacoes_crud_e_contador(db):
    db.add_notification("estudei X", kind="study", link="http://x")
    db.add_notification("lacuna Y", kind="gap")
    assert db.unread_count() == 2
    items = db.list_notifications()
    assert len(items) == 2
    assert items[0]["message"] == "lacuna Y"  # mais recente primeiro
    assert items[0]["read"] is False
    # marca todas como lidas
    assert db.mark_notifications_read() == 2
    assert db.unread_count() == 0
    assert db.list_notifications(unread_only=True) == []
    # limpa
    assert db.clear_notifications() == 2
    assert db.list_notifications() == []


def test_notificacoes_poda_excedente(db):
    db.NOTIF_KEEP = 5  # reduz o teto para testar a poda
    for i in range(12):
        db.add_notification(f"evento {i}", kind="info")
    items = db.list_notifications(limit=100)
    assert len(items) == 5  # só as 5 mais recentes sobraram
    assert items[0]["message"] == "evento 11"  # a mais recente


def test_agendamento_crud(db):
    s = db.add_schedule("estudar rust", "07:30")
    assert s["topic"] == "estudar rust"
    lst = db.list_schedules()
    assert len(lst) == 1 and lst[0]["time_of_day"] == "07:30"
    assert db.toggle_schedule(s["id"]) is True
    assert db.list_schedules()[0]["enabled"] is False
    assert db.delete_schedule(s["id"]) is True
    assert db.list_schedules() == []


def test_due_schedules_dispara_no_horario(db):
    from datetime import datetime
    db.add_schedule("tópico da manhã", "08:00")
    # Antes da hora → não dispara
    assert db.due_schedules(datetime(2026, 6, 19, 7, 59)) == []
    # Na hora → dispara
    due = db.due_schedules(datetime(2026, 6, 19, 8, 0))
    assert len(due) == 1 and due[0]["topic"] == "tópico da manhã"


def test_due_schedules_nao_repete_no_mesmo_dia(db):
    from datetime import datetime
    s = db.add_schedule("uma vez ao dia", "06:00")
    when = datetime(2026, 6, 19, 9, 0)
    assert len(db.due_schedules(when)) == 1
    db.mark_schedule_ran(s["id"], when)
    # Mesmo dia, mais tarde → não dispara de novo
    assert db.due_schedules(datetime(2026, 6, 19, 23, 0)) == []
    # Dia seguinte → dispara de novo
    assert len(db.due_schedules(datetime(2026, 6, 20, 6, 30))) == 1


def test_due_schedules_ignora_desativado(db):
    from datetime import datetime
    s = db.add_schedule("pausado", "05:00")
    db.toggle_schedule(s["id"])  # desativa
    assert db.due_schedules(datetime(2026, 6, 19, 12, 0)) == []


def test_cleanup_remove_meta_orfao(db):
    """Título sem mensagens é considerado fantasma e removido."""
    db.save_session_title("fantasma", "Sessão sem mensagens")
    assert db.cleanup_orphan_meta() == 1
    assert db.cleanup_orphan_meta() == 0


def test_lista_inclui_chats_antigos(db):
    """days=0 lista todo o histórico — chats antigos não somem da sidebar."""
    from datetime import datetime, timezone
    from src.storage import Session, SessionMessage
    with Session(db.engine) as s:
        s.add(SessionMessage(session_id="velho", role="user", content="pergunta antiga",
                             timestamp=datetime(2020, 1, 1, tzinfo=timezone.utc)))
        s.commit()
    ids = [x["session_id"] for x in db.list_sessions(days=0)]
    assert "velho" in ids
    # Com janela curta, o chat antigo de 2020 fica de fora.
    assert "velho" not in [x["session_id"] for x in db.list_sessions(days=7)]
