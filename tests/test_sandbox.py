"""Testes do sandbox de automelhoria (cópia isolada → diff → aplicar/descartar)."""

import os

import pytest

from src import sandbox as sb


@pytest.fixture
def project(tmp_path):
    """Um 'projeto' falso com código, um teste, segredo e runtime."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=abc\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "apolo.db").write_text("binário", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("cache", encoding="utf-8")
    return str(tmp_path)


def test_sandbox_copia_codigo_mas_nao_segredos_nem_runtime(project):
    s = sb.create_sandbox(project)
    assert os.path.isfile(os.path.join(s, "src", "mod.py"))
    assert os.path.isfile(os.path.join(s, "app.py"))
    # Segredos e runtime NÃO são copiados.
    assert not os.path.exists(os.path.join(s, ".env"))
    assert not os.path.exists(os.path.join(s, "data"))
    assert not os.path.exists(os.path.join(s, "__pycache__"))
    sb.discard_sandbox(s)


def test_diff_detecta_added_modified_deleted(project):
    s = sb.create_sandbox(project)
    # modifica, adiciona e remove na sandbox
    (open(os.path.join(s, "src", "mod.py"), "w", encoding="utf-8")).write("x = 2\n")
    (open(os.path.join(s, "novo.py"), "w", encoding="utf-8")).write("print('novo')\n")
    os.remove(os.path.join(s, "app.py"))
    changes = {c["path"]: c["status"] for c in sb.diff_sandbox(s, project)}
    assert changes["src/mod.py"] == "modified"
    assert changes["novo.py"] == "added"
    assert changes["app.py"] == "deleted"
    sb.discard_sandbox(s)


def test_diff_vazio_quando_identico(project):
    s = sb.create_sandbox(project)
    assert sb.diff_sandbox(s, project) == []
    sb.discard_sandbox(s)


def test_apply_aplica_mudancas_no_projeto(project):
    s = sb.create_sandbox(project)
    open(os.path.join(s, "src", "mod.py"), "w", encoding="utf-8").write("x = 99\n")
    open(os.path.join(s, "novo.py"), "w", encoding="utf-8").write("y = 1\n")
    res = sb.apply_sandbox(s, project)
    assert res["count"] == 2
    assert open(os.path.join(project, "src", "mod.py"), encoding="utf-8").read() == "x = 99\n"
    assert os.path.isfile(os.path.join(project, "novo.py"))
    sb.discard_sandbox(s)


def test_apply_seletivo_so_aplica_os_escolhidos(project):
    s = sb.create_sandbox(project)
    open(os.path.join(s, "src", "mod.py"), "w", encoding="utf-8").write("x = 7\n")
    open(os.path.join(s, "novo.py"), "w", encoding="utf-8").write("z = 0\n")
    res = sb.apply_sandbox(s, project, paths=["novo.py"])
    assert res["applied"] == ["novo.py"]
    # mod.py NÃO foi aplicado (não estava na lista)
    assert open(os.path.join(project, "src", "mod.py"), encoding="utf-8").read() == "x = 1\n"
    sb.discard_sandbox(s)


def test_apply_delecao_remove_do_projeto(project):
    s = sb.create_sandbox(project)
    os.remove(os.path.join(s, "app.py"))
    sb.apply_sandbox(s, project)
    assert not os.path.exists(os.path.join(project, "app.py"))
    sb.discard_sandbox(s)


def test_file_pair_devolve_antigo_e_novo(project):
    s = sb.create_sandbox(project)
    with open(os.path.join(s, "src", "mod.py"), "w", encoding="utf-8") as fh:
        fh.write("x = 2\n")
    old, new = sb.file_pair(s, project, "src/mod.py")
    assert old.strip() == "x = 1" and new.strip() == "x = 2"
    sb.discard_sandbox(s)


def test_discard_remove_a_sandbox(project):
    s = sb.create_sandbox(project)
    parent = os.path.dirname(s)
    assert sb.discard_sandbox(s) is True
    assert not os.path.exists(parent)


def test_discard_recusa_pasta_que_nao_e_sandbox(project):
    # Proteção: não apaga uma pasta qualquer que não tenha o prefixo de sandbox.
    assert sb.discard_sandbox(project) is False
    assert os.path.exists(project)
