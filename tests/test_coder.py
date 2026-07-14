"""Testes do workspace de codificação — foco em confinamento (path traversal) e ferramentas."""

import pytest
from src.coder import CoderWorkspace, extract_fenced, make_diff, normalize_cmd


@pytest.fixture
def ws(tmp_path):
    return CoderWorkspace(root=str(tmp_path / "workspace"))


# ── is_empty: barreira contra rodar o loop num workspace vazio ────
def test_is_empty_workspace_novo(ws):
    assert ws.is_empty() is True


def test_is_empty_falso_com_arquivo(ws):
    ws.write_file("app.py", "print('oi')\n")
    assert ws.is_empty() is False


def test_is_empty_ignora_git_e_pycache(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    ws = CoderWorkspace(root=str(root))
    assert ws.is_empty() is True   # só lixo de VCS/cache — nenhum arquivo "real"


# ── Segurança: confinamento ───────────────────────────────────
def test_escrever_e_ler(ws):
    msg = ws.write_file("app.py", "print('oi')\n")
    assert "OK" in msg
    assert "print('oi')" in ws.read_file("app.py")


def test_subdiretorio(ws):
    ws.write_file("src/util.py", "x = 1\n")
    assert "x = 1" in ws.read_file("src/util.py")


def test_path_traversal_bloqueado(ws):
    with pytest.raises(ValueError):
        ws._safe("../segredo.txt")
    with pytest.raises(ValueError):
        ws._safe("../../etc/passwd")
    with pytest.raises(ValueError):
        ws._safe("subdir/../../fora.txt")  # traversal disfarçado dentro de subpasta


def test_traversal_retorna_mensagem_sem_levantar(ws):
    # As ferramentas confinam e respondem com mensagem — não estouram exceção (evita 500).
    assert "fora do workspace" in ws.read_file("../../etc/passwd")
    assert "fora do workspace" in ws.list_dir("../..")
    assert "fora do workspace" in ws.write_file("../escapou.py", "x=1")


def test_barra_inicial_vira_relativo(ws):
    # "/app.py" deve ser tratado como relativo à raiz, não absoluto.
    p = ws._safe("/app.py")
    assert p.name == "app.py"
    assert str(ws.root) in str(p)


def test_extensao_nao_permitida(ws):
    msg = ws.write_file("malware.exe", "binario")
    assert "não permitida" in msg


def test_ler_inexistente(ws):
    assert "não encontrado" in ws.read_file("nada.py")


def test_listar(ws):
    ws.write_file("a.py", "1")
    ws.write_file("b.py", "2")
    listing = ws.list_dir(".")
    assert "a.py" in listing and "b.py" in listing


# ── Shell ─────────────────────────────────────────────────────
def test_run_cmd_sucesso(ws):
    ok, out = ws.run_cmd("python -c \"print(2+2)\"")
    assert ok
    assert "4" in out


def test_run_cmd_falha(ws):
    ok, out = ws.run_cmd("python -c \"raise SystemExit(3)\"")
    assert not ok


def test_run_cmd_bloqueado(ws):
    ok, out = ws.run_cmd("rm -rf /")
    assert not ok
    assert "bloqueado" in out


def test_run_cmd_stream_linhas_e_done(ws):
    events = list(ws.run_cmd_stream('python -c "print(1); print(2)"'))
    kinds = [k for k, _ in events]
    assert kinds[-1] == "done"
    assert events[-1][1] is True  # sucesso
    lines = [v for k, v in events if k == "line"]
    assert "1" in lines and "2" in lines


def test_normalize_cmd():
    assert normalize_cmd("pytest -q") == "python -m pytest -q"
    assert normalize_cmd("pytest") == "python -m pytest"
    assert normalize_cmd("pip install requests") == "python -m pip install requests"
    # não mexe em comandos que apenas contêm a palavra
    assert normalize_cmd("python run_pytest.py") == "python run_pytest.py"
    assert normalize_cmd("echo pytest") == "echo pytest"
    assert normalize_cmd("python -c \"print(1)\"") == "python -c \"print(1)\""


def test_run_cmd_stream_bloqueado(ws):
    events = list(ws.run_cmd_stream("mkfs /dev/sda"))
    assert events[-1] == ("done", False)
    assert any("bloqueado" in v for k, v in events if k == "line")


def test_run_roda_no_workspace(ws):
    ws.write_file("marca.txt", "presente")
    ok, out = ws.run_cmd("python -c \"import os; print(os.path.exists('marca.txt'))\"")
    assert ok and "True" in out


# ── Histórico, undo e troca de raiz ───────────────────────────
def test_delete_file_reversivel(ws):
    ws.write_file("velho.py", "conteudo importante\n")
    msg = ws.delete_file("velho.py")
    assert "OK" in msg
    assert "velho.py" not in ws.list_dir(".")
    # undo restaura o arquivo apagado
    ws.undo_last()
    assert "conteudo importante" in ws.read_file("velho.py")


def test_delete_file_inexistente(ws):
    assert "não encontrado" in ws.delete_file("nada.py")


def test_rename_file(ws):
    ws.write_file("antigo.py", "conteudo X\n")
    msg = ws.rename_file("antigo.py", "novo.py")
    assert "OK" in msg
    assert "antigo.py" not in ws.list_dir(".")
    assert "conteudo X" in ws.read_file("novo.py")


def test_rename_file_subdir(ws):
    ws.write_file("a.py", "z=1\n")
    ws.rename_file("a.py", "src/b.py")
    assert "z=1" in ws.read_file("src/b.py")
    assert "a.py" not in ws.list_dir(".")


def test_rename_inexistente(ws):
    assert "não encontrado" in ws.rename_file("nada.py", "x.py")


def test_search_replace(ws):
    ws.write_file("a.py", "x = old_name()\ny = old_name\n")
    ws.write_file("b.py", "z = old_name()\n")
    ws.write_file("c.py", "nada aqui\n")
    res = ws.search_replace("old_name", "new_name")
    assert res["ok"] and res["files_changed"] == 2 and res["count"] == 3
    assert "new_name" in ws.read_file("a.py") and "old_name" not in ws.read_file("a.py")
    assert "nada aqui" in ws.read_file("c.py")  # inalterado


def test_search_replace_reversivel(ws):
    ws.write_file("a.py", "valor = ANTIGO\n")
    ws.search_replace("ANTIGO", "NOVO")
    assert "NOVO" in ws.read_file("a.py")
    ws.undo_last()  # desfaz a substituição (1 arquivo alterado)
    assert "ANTIGO" in ws.read_file("a.py")


def test_search_replace_vazio(ws):
    res = ws.search_replace("", "x")
    assert res["ok"] is False


def test_undo_arquivo_novo_remove(ws):
    ws.write_file("novo.py", "x = 1\n")
    assert "novo.py" in ws.list_dir(".")
    assert len(ws.list_changes()) == 1
    r = ws.undo_last()
    assert r["ok"] and r["restored"] == "removido"
    assert "novo.py" not in ws.list_dir(".")
    assert ws.list_changes() == []


def test_undo_alteracao_reverte_conteudo(ws):
    ws.write_file("c.py", "VERSION = 1\n")
    ws.write_file("c.py", "VERSION = 2\n")
    assert "VERSION = 2" in ws.current_content("c.py")
    ws.undo_last()
    assert "VERSION = 1" in ws.current_content("c.py")  # voltou ao snapshot anterior


def test_undo_file_especifico(ws):
    ws.write_file("a.py", "a=1\n")
    ws.write_file("b.py", "b=1\n")
    r = ws.undo_file("a.py")
    assert r["ok"]
    assert "a.py" not in ws.list_dir(".")
    assert "b.py" in ws.list_dir(".")  # b intacto


def test_undo_all(ws):
    ws.write_file("x.py", "1")
    ws.write_file("y.py", "2")
    r = ws.undo_all()
    assert r["reverted"] == 2
    assert ws.list_dir(".") == "(vazio)"


def test_undo_sem_historico(ws):
    assert ws.undo_last()["ok"] is False


def test_set_root_valido_e_invalido(ws, tmp_path):
    novo = tmp_path / "projeto_real"
    novo.mkdir()
    (novo / "existente.py").write_text("ja existia\n")
    r = ws.set_root(str(novo))
    assert r["ok"]
    assert "existente.py" in ws.list_dir(".")
    assert ws.list_changes() == []  # histórico limpo ao trocar raiz
    assert ws.set_root(str(tmp_path / "nao_existe"))["ok"] is False


# ── Helper de extração ────────────────────────────────────────
def test_extract_fenced():
    assert extract_fenced("texto\n```python\nprint(1)\n```\nfim") == "print(1)\n"
    assert extract_fenced("```\nsem linguagem\n```") == "sem linguagem\n"
    assert extract_fenced("sem bloco") is None


# ── Parser de ações do Coder (no app.py) ──────────────────────
def test_parse_coder_actions():
    from routers.coder import parse_coder_action as _parse_coder_action
    assert _parse_coder_action("LISTAR .")[:2] == ("list", ".")
    assert _parse_coder_action("LER src/app.py")[:2] == ("read", "src/app.py")
    assert _parse_coder_action("RODAR pytest -q")[:2] == ("run", "pytest -q")
    t, arg, body = _parse_coder_action("ESCREVER a.py\n```python\nx=1\n```")
    assert (t, arg) == ("write", "a.py") and "x=1" in body
    assert _parse_coder_action("Pronto, terminei a tarefa.")[0] == "done"


def test_current_content(ws):
    assert ws.current_content("novo.py") == ""
    ws.write_file("x.py", "a = 1\n")
    assert ws.current_content("x.py") == "a = 1\n"


def test_make_diff_novo_arquivo():
    d = make_diff("", "linha1\nlinha2\n", "novo.py")
    assert d["is_new"] is True
    assert d["added"] == 2 and d["removed"] == 0
    assert "+linha1" in d["text"]


def test_make_diff_alteracao():
    d = make_diff("a = 1\nb = 2\n", "a = 1\nb = 99\n", "x.py")
    assert d["is_new"] is False
    assert d["added"] == 1 and d["removed"] == 1
    assert "-b = 2" in d["text"] and "+b = 99" in d["text"]


def test_search_conteudo(ws):
    ws.write_file("a.py", "def login():\n    pass\n")
    ws.write_file("b.py", "x = login()\n")
    out = ws.search("login")
    assert "a.py:1:" in out and "b.py:1:" in out
    assert ws.search("inexistente_xyz").startswith("(nenhum")


def test_search_curto(ws):
    assert "curta" in ws.search("a")


def test_git_status_nao_repo(ws):
    st = ws.git_status()
    assert st["is_repo"] is False


def test_git_repo_status_e_diff(ws):
    import subprocess, shutil
    if not shutil.which("git"):
        return  # ambiente sem git → pula
    r = ws.root
    def g(*a):
        subprocess.run(["git", *a], cwd=str(r), capture_output=True, text=True)
    g("init")
    g("config", "user.email", "t@t.com")
    g("config", "user.name", "t")
    ws.write_file("f.py", "a = 1\n")
    g("add", "."); g("commit", "-m", "init")
    st = ws.git_status()
    assert st["is_repo"] is True
    assert st["dirty"] is False  # tudo commitado
    ws.write_file("f.py", "a = 2\n")  # altera
    st2 = ws.git_status()
    assert st2["dirty"] is True
    assert "a = 2" in ws.git_diff() or "a = 1" in ws.git_diff()  # diff mostra a mudança


def test_list_files(ws):
    ws.write_file("a.py", "1")
    ws.write_file("src/b.py", "2")
    ws.write_file("src/sub/c.md", "3")
    files = ws.list_files()
    assert files == ["a.py", "src/b.py", "src/sub/c.md"]  # plano, posix, ordenado


def test_find_files(ws):
    ws.write_file("src/models/user.py", "u=1\n")
    ws.write_file("src/views.py", "v=1\n")
    out = ws.find_files("user")
    assert "src/models/user.py" in out
    assert ws.find_files("zzz").startswith("(nenhum")


def test_parse_search_find():
    from routers.coder import parse_coder_action as _parse_coder_action
    assert _parse_coder_action("BUSCAR def login")[:2] == ("search", "def login")
    assert _parse_coder_action("ACHAR user.py")[:2] == ("find", "user.py")
    assert _parse_coder_action("PROCURAR TODO")[:2] == ("search", "TODO")


def test_parse_delete_replace():
    from routers.coder import parse_coder_action as _parse_coder_action
    assert _parse_coder_action("APAGAR old.py")[:2] == ("delete", "old.py")
    assert _parse_coder_action("REMOVER temp.txt")[:2] == ("delete", "temp.txt")
    t, find, rep = _parse_coder_action("SUBSTITUIR foo ==> bar")
    assert (t, find, rep) == ("replace", "foo", "bar")
    # malformado (sem ==>) → não vira replace
    assert _parse_coder_action("SUBSTITUIR só isso")[0] == "done"


def test_parse_move():
    from routers.coder import parse_coder_action as _parse_coder_action
    assert _parse_coder_action("MOVER a.py ==> b.py")[:3] == ("move", "a.py", "b.py")
    assert _parse_coder_action("MOVER a.py b.py")[:3] == ("move", "a.py", "b.py")
    assert _parse_coder_action("RENOMEAR x.py ==> y.py")[:3] == ("move", "x.py", "y.py")


def test_make_diff_truncamento():
    novo = "\n".join(f"l{i}" for i in range(500))
    d = make_diff("", novo, "big.py", max_lines=50)
    assert "truncado" in d["text"]


def test_parse_coder_tolerante_a_marcadores_e_typos():
    from routers.coder import parse_coder_action as _parse_coder_action
    # numeração de lista e flexão/typo dos verbos
    assert _parse_coder_action("1. LISTAR .")[0] == "list"
    assert _parse_coder_action("- RODRAR pytest")[:2] == ("run", "pytest")
    assert _parse_coder_action("**ESCREVA b.py**\n```\noi\n```")[:2] == ("write", "b.py**")
    assert _parse_coder_action("LEIA config.json")[:2] == ("read", "config.json")
