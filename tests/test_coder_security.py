"""Testes de segurança do sandbox do Coder — bordas dos comandos bloqueados e
confinamento do open_in_vscode. Código de segurança merece testes de borda.
"""

import pytest

from src.coder import CoderWorkspace


@pytest.fixture
def ws(tmp_path):
    return CoderWorkspace(str(tmp_path))


# ── Comandos catastróficos: TODOS devem ser bloqueados ───────────
@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    "rm -rf /home",
    "rm -rf ~",
    "rm -rf ~/Documents",
    ":(){ :|:& };:",          # fork bomb
    "mkfs.ext4 /dev/sda1",
    "dd if=/dev/zero of=/dev/sda",
    "shutdown now",
    "shutdown -h now",
    "reboot",
    "echo x > /dev/sda",
    "chmod -R 777 /",
    "git push origin main",
    "git push",
])
def test_comandos_catastroficos_bloqueados(ws, cmd):
    assert ws._blocked_reason(cmd) is not None, f"deveria bloquear: {cmd}"


# ── Comandos seguros: NÃO devem ser bloqueados (sem falsos positivos) ──
@pytest.mark.parametrize("cmd", [
    "rm arquivo.txt",
    "rm -f temp.log",
    "git status",
    "git commit -m 'msg'",
    "git diff",
    "git add .",
    "python app.py",
    "python -m pytest -q",
    "ls -la",
    "echo 'rm -rf isso é só texto'",   # menção em string, não execução
    "npm install",
    "mkdir nova_pasta",
])
def test_comandos_seguros_nao_bloqueados(ws, cmd):
    assert ws._blocked_reason(cmd) is None, f"NÃO deveria bloquear: {cmd}"


def test_run_cmd_bloqueia_catastrofico(ws):
    ok, out = ws.run_cmd("rm -rf /")
    assert ok is False
    assert "bloqueado" in out.lower()


def test_run_cmd_stream_bloqueia_catastrofico(ws):
    events = list(ws.run_cmd_stream("git push"))
    # Deve terminar com done=False e nunca executar.
    assert ("done", False) in events
    assert not any(kind == "line" and "Everything up-to-date" in str(val)
                   for kind, val in events)


# ── open_in_vscode: confinamento ao workspace ────────────────────
def test_vscode_traversal_bloqueado(ws):
    res = ws.open_in_vscode("../../fora.py")
    assert res["ok"] is False
    assert "fora do workspace" in res["error"]


def test_vscode_arquivo_inexistente(ws):
    res = ws.open_in_vscode("nao_existe.py")
    assert res["ok"] is False
    assert "não existe" in res["error"]


# ── Guarda anti-reescrita catastrófica ───────────────────────────
def test_write_bloqueia_encolhimento_catastrofico(ws):
    big = "\n".join(f"linha {i}" for i in range(40))   # 40 linhas
    ws.write_file("modulo.py", big)
    out = ws.write_file("modulo.py", "x = 1\n")          # encolhe p/ ~2 linhas
    assert "BLOQUEADO" in out
    # O arquivo original NÃO foi tocado.
    assert "linha 39" in ws.current_content("modulo.py")


def test_write_permite_encolhimento_com_allow_shrink(ws):
    big = "\n".join(f"linha {i}" for i in range(40))
    ws.write_file("modulo.py", big)
    out = ws.write_file("modulo.py", "x = 1\n", allow_shrink=True)
    assert out.startswith("OK")
    assert ws.current_content("modulo.py").strip() == "x = 1"


def test_write_permite_edicao_normal(ws):
    big = "\n".join(f"linha {i}" for i in range(40))
    ws.write_file("modulo.py", big)
    # Encolhimento pequeno (remove ~5 linhas) é permitido.
    menor = "\n".join(f"linha {i}" for i in range(35))
    assert ws.write_file("modulo.py", menor).startswith("OK")


def test_write_arquivo_pequeno_nao_e_protegido(ws):
    ws.write_file("p.py", "a = 1\nb = 2\n")   # arquivo trivial (<20 linhas)
    assert ws.write_file("p.py", "c = 3\n").startswith("OK")


def test_write_novo_arquivo_sempre_ok(ws):
    assert ws.write_file("novo.py", "print(1)\n").startswith("OK")


def test_vscode_parse_linha_passa_confinamento(ws, monkeypatch):
    # IMPORTANTE: o teste NUNCA pode lançar o VS Code de verdade. Forçamos a CLI
    # `code` a parecer ausente (which→None) — então open_in_vscode chega até a
    # checagem do PATH (provando que passou pelo parse de linha e pelo confinamento)
    # sem nunca spawnar um processo.
    monkeypatch.setattr("shutil.which", lambda *_a, **_k: None)
    ws.write_file("f.py", "print(1)\nprint(2)\nprint(3)\n")
    res = ws.open_in_vscode("f.py:2")
    assert res["ok"] is False
    assert "PATH" in res["error"] or "code" in res["error"]
