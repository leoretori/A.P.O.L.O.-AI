"""Roteamento do takeover progressivo (M27): Nano primeiro, professor no fallback,
sempre registrando quem serviu. Determinístico — funções e recorder injetados."""
from src.nanollm.routing import route_task, task_enabled


def _rec():
    seen = []
    return seen, lambda task, by: seen.append((task, by))


def test_nano_serve_quando_produz_resultado():
    seen, rec = _rec()
    out, by = route_task("title", lambda: "Título Bom", lambda: "PROF", recorder=rec)
    assert out == "Título Bom" and by == "nano"
    assert seen == [("title", "nano")]


def test_fallback_quando_nano_recusa_com_none():
    seen, rec = _rec()
    out, by = route_task("title", lambda: None, lambda: "PROF", recorder=rec)
    assert out == "PROF" and by == "teacher"       # portão de qualidade do Nano recusou
    assert seen == [("title", "teacher")]


def test_fallback_quando_nano_explode():
    def boom():
        raise RuntimeError("nano quebrou")
    out, by = route_task("title", boom, lambda: "PROF")
    assert out == "PROF" and by == "teacher"        # exceção nunca derruba a tarefa


def test_gate_desliga_familia(monkeypatch):
    monkeypatch.setenv("NANO_TASKS_OFF", "title,tags")
    assert task_enabled("title") is False
    assert task_enabled("sector") is True
    # com a família desligada, nem tenta o Nano (nano_fn não é chamado)
    out, by = route_task("title", lambda: (_ for _ in ()).throw(AssertionError("não devia tentar")),
                         lambda: "PROF")
    assert out == "PROF" and by == "teacher"


def test_nano_indisponivel_vai_direto_ao_professor():
    seen, rec = _rec()
    out, by = route_task("title", lambda: "X", lambda: "PROF",
                         recorder=rec, nano_available=False)
    assert out == "PROF" and by == "teacher"
    assert seen == [("title", "teacher")]
