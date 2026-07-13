"""desktop.py: launcher de janela nativa (sem navegador). Cobre a decisão
`started_here` — se o script SUBIU o servidor ou só abriu uma janela por cima de
um servidor já rodando (ex.: o Leo já tinha app.py aberto à mão). Os avisos de
"fechar isso encerra o A.P.O.L.O." só podem ser verdadeiros no primeiro caso —
mostrar isso quando o servidor é de outro processo seria enganoso."""
import sys

import pytest

import desktop


@pytest.fixture(autouse=True)
def _no_real_server(monkeypatch):
    # Nunca deixa o teste subir um uvicorn de verdade nem abrir navegador. `webbrowser`
    # é importado sob demanda DENTRO de main() — o alvo pelo caminho de string
    # ("webbrowser.open") pega o módulo real via sys.modules, que é o mesmo objeto
    # que esse `import webbrowser` local vai resolver.
    monkeypatch.setattr(desktop.threading, "Thread",
                        lambda target, daemon: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr("webbrowser.open", lambda url: None)


def test_started_here_quando_porta_fechada_sobe_o_servidor(monkeypatch, capsys):
    monkeypatch.setattr(desktop, "_port_open", lambda timeout=0.6: False)
    monkeypatch.setattr(desktop, "_wait_until_up", lambda timeout=60: True)
    monkeypatch.setitem(sys.modules, "webview", None)   # simula lib ausente
    monkeypatch.setattr("time.sleep",
                        lambda s: (_ for _ in ()).throw(KeyboardInterrupt))
    rc = desktop.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Iniciando o A.P.O.L.O." in out
    assert "Deixe este terminal ABERTO" in out   # subimos o servidor -> aviso vale


def test_nao_started_here_quando_porta_ja_aberta_nao_sobe_de_novo(monkeypatch, capsys):
    monkeypatch.setattr(desktop, "_port_open", lambda timeout=0.6: True)
    monkeypatch.setitem(sys.modules, "webview", None)   # simula lib ausente
    rc = desktop.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Iniciando o A.P.O.L.O." not in out          # não subiu de novo
    assert "Deixe este terminal ABERTO" not in out       # servidor não é nosso
    assert "Abrindo no navegador" in out


def test_wait_until_up_falha_retorna_erro(monkeypatch, capsys):
    monkeypatch.setattr(desktop, "_port_open", lambda timeout=0.6: False)
    monkeypatch.setattr(desktop, "_wait_until_up", lambda timeout=60: False)
    rc = desktop.main()
    assert rc == 1
    assert "não subiu a tempo" in capsys.readouterr().out


def _fake_webview_module():
    calls = {"create_window": None, "start": 0}

    class _FakeWebview:
        @staticmethod
        def create_window(title, url, **kw):
            calls["create_window"] = (title, url)

        @staticmethod
        def start():
            calls["start"] += 1

    return _FakeWebview, calls


def test_webview_disponivel_started_here_mensagem_correta(monkeypatch, capsys):
    fake, calls = _fake_webview_module()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(desktop, "_port_open", lambda timeout=0.6: False)
    monkeypatch.setattr(desktop, "_wait_until_up", lambda timeout=60: True)
    rc = desktop.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert calls["start"] == 1
    assert "Fechá-la encerra o app." in out
    assert "já estava rodando" not in out


def test_webview_disponivel_servidor_externo_mensagem_correta(monkeypatch, capsys):
    fake, calls = _fake_webview_module()
    monkeypatch.setitem(sys.modules, "webview", fake)
    monkeypatch.setattr(desktop, "_port_open", lambda timeout=0.6: True)
    rc = desktop.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert calls["start"] == 1
    assert "já estava rodando em outro processo" in out
    assert "Fechá-la encerra o app." not in out
