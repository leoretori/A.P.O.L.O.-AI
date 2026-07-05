"""Testes das melhorias de autonomia do Coder: leitura parcial de arquivos
grandes, parser LER com faixa de linhas, poda da memória de lições e o
diário de bordo de tarefas (storage)."""

import pytest

from src.coder import CoderWorkspace
from src.lessons import LessonMemory
from src.storage import DatabaseManager


@pytest.fixture
def ws(tmp_path):
    return CoderWorkspace(str(tmp_path))


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/test.db")


# ── LER parcial (faixa de linhas) ─────────────────────────────────
def _big_file(ws, n=300):
    ws.write_file("grande.py", "\n".join(f"linha_{i} = {i}" for i in range(1, n + 1)))


def test_read_file_faixa_de_linhas(ws):
    _big_file(ws)
    out = ws.read_file("grande.py", start=10, end=12)
    assert "(linhas 10-12 de 300)" in out
    assert "linha_10" in out and "linha_12" in out
    assert "linha_9 " not in out and "linha_13" not in out


def test_read_file_faixa_alem_do_fim(ws):
    _big_file(ws, n=20)
    out = ws.read_file("grande.py", start=500, end=600)
    assert "20 linhas" in out


def test_read_file_faixa_fim_ajustado(ws):
    _big_file(ws, n=20)
    out = ws.read_file("grande.py", start=18, end=99)
    assert "(linhas 18-20 de 20)" in out


def test_read_file_truncado_ensina_a_continuar(ws):
    _big_file(ws, n=800)   # bem maior que max_chars=6000
    out = ws.read_file("grande.py")
    assert "use LER grande.py:" in out   # dica acionável de leitura parcial


def test_read_file_pequeno_sem_ruido(ws):
    ws.write_file("p.py", "x = 1\n")
    out = ws.read_file("p.py")
    assert out == "x = 1\n"
    assert "truncado" not in out


# ── Parser: LER caminho:início-fim ────────────────────────────────
def test_parse_ler_com_faixa():
    from app import _parse_coder_action
    action, arg, payload = _parse_coder_action("LER src/app.py:40-120")
    assert (action, arg, payload) == ("read", "src/app.py", "40-120")


def test_parse_ler_sem_faixa_continua_igual():
    from app import _parse_coder_action
    action, arg, payload = _parse_coder_action("LER src/app.py")
    assert (action, arg, payload) == ("read", "src/app.py", "")


# ── Parser: CONSULTAR (base de conhecimento / RAG) ────────────────
def test_parse_consultar():
    from app import _parse_coder_action
    action, arg, payload = _parse_coder_action("CONSULTAR como fazer streaming SSE em FastAPI")
    assert action == "consult"
    assert arg == "como fazer streaming SSE em FastAPI"


def test_parse_consultar_flexao_e_lembrar():
    from app import _parse_coder_action
    # tolera flexão do verbo (CONSULTE) e o sinônimo LEMBRAR
    assert _parse_coder_action("CONSULTE decorators em python")[0] == "consult"
    assert _parse_coder_action("LEMBRAR o que aprendi sobre asyncio")[0] == "consult"


def test_parse_consultar_com_marcador_de_lista():
    from app import _parse_coder_action
    # modelos leves às vezes prefixam com "1. " ou "- "
    action, arg, _ = _parse_coder_action("- CONSULTAR circuit breaker resilience")
    assert action == "consult"
    assert arg == "circuit breaker resilience"


def test_consultar_nao_colide_com_buscar():
    from app import _parse_coder_action
    # BUSCAR (grep no workspace) e CONSULTAR (RAG) são ações distintas
    assert _parse_coder_action("BUSCAR def soma")[0] == "search"
    assert _parse_coder_action("CONSULTAR def soma")[0] == "consult"


# ── Parser: BUSCAR_WEB (pesquisa na web) ──────────────────────────
def test_parse_buscar_web():
    from app import _parse_coder_action
    action, arg, _ = _parse_coder_action("BUSCAR_WEB: FastAPI StreamingResponse SSE example")
    assert action == "web"
    assert arg == "FastAPI StreamingResponse SSE example"


def test_parse_buscar_web_sem_dois_pontos():
    from app import _parse_coder_action
    action, arg, _ = _parse_coder_action("BUSCAR_WEB pydantic v2 migration")
    assert action == "web"
    assert arg == "pydantic v2 migration"


def test_parse_buscar_web_com_marcador():
    from app import _parse_coder_action
    action, arg, _ = _parse_coder_action("- BUSCAR_WEB: como corrigir ImportError X")
    assert action == "web"
    assert arg == "como corrigir ImportError X"


def test_buscar_web_nao_colide_com_grep():
    from app import _parse_coder_action
    # BUSCAR (grep) e BUSCAR_WEB (web) são distintos; grep NUNCA vira web
    assert _parse_coder_action("BUSCAR web handler")[0] == "search"
    assert _parse_coder_action("BUSCAR_WEB web handler")[0] == "web"


# ── Poda da memória de lições ─────────────────────────────────────
def test_licoes_poda_no_cap(tmp_path):
    mem = LessonMemory(str(tmp_path / "l.db"), max_rows=5)
    for i in range(8):
        mem.add(f"tarefa {i}", f"Lição número {i} sobre o assunto tarefa-{i} deste workspace.")
    assert mem.count() == 5
    # As mais recentes sobrevivem (poda remove as antigas menos usadas).
    lessons = " ".join(l["lesson"] for l in mem.recent(10))
    assert "número 7" in lessons and "número 0" not in lessons


def test_licoes_poda_protege_regressao(tmp_path):
    mem = LessonMemory(str(tmp_path / "l.db"), max_rows=3)
    mem.add("tarefa regressao", "Regressão antiga: parser quebrou a suíte de testes uma vez.",
            kind="regression")
    for i in range(4):
        mem.add(f"tarefa {i}", f"Reflexão comum número {i} sobre este workspace em particular.")
    lessons = " ".join(l["lesson"] for l in mem.recent(10))
    # A regressão (mais antiga que todas) sobrevive; reflexões antigas caem.
    assert "Regressão antiga" in lessons
    assert mem.count() == 3


# ── Diário de bordo do Coder (storage) ────────────────────────────
def test_coder_task_salva_e_lista(db):
    db.save_coder_task("criar CLI de soma", model="qwen2.5-coder:3b", steps=5,
                       wrote=True, ran=True, reverted=False, duration_s=42.7,
                       summary="Criei soma.py com testes.")
    tasks = db.get_coder_tasks()
    assert len(tasks) == 1
    t = tasks[0]
    assert t["task"] == "criar CLI de soma"
    assert t["steps"] == 5 and t["wrote"] is True and t["reverted"] is False
    assert t["duration_s"] == 42.7


def test_coder_stats_taxa_de_sucesso(db):
    for rev in (False, False, False, True):
        db.save_coder_task("t", reverted=rev)
    st = db.get_coder_stats()
    assert st["total"] == 4 and st["reverted"] == 1
    assert st["success_rate"] == 75


def test_coder_stats_vazio(db):
    st = db.get_coder_stats()
    assert st["total"] == 0 and st["success_rate"] is None
    assert st["trend"] is None


def test_coder_stats_tendencia(db):
    # 10 antigas: 5 revertidas (50%) → 10 recentes: 1 revertida (90%) = melhora
    for i in range(10):
        db.save_coder_task(f"antiga {i}", reverted=(i < 5))
    for i in range(10):
        db.save_coder_task(f"recente {i}", reverted=(i == 0))
    st = db.get_coder_stats(window=10)
    assert st["recent_rate"] == 90 and st["prev_rate"] == 50
    assert st["trend"] == 40


def test_coder_stats_tendencia_sem_janela_anterior(db):
    for i in range(5):
        db.save_coder_task(f"t{i}")
    st = db.get_coder_stats(window=10)
    assert st["recent_rate"] == 100
    assert st["prev_rate"] is None and st["trend"] is None


# ── EDITAR falho com dica do trecho mais parecido ─────────────────
def test_edit_dica_trecho_parecido(ws):
    ws.write_file("calc.py", "def soma(a, b):\n    return a + b\n\n"
                             "def sub(a, b):\n    return a - b\n")
    # O modelo errou: esqueceu os espaços da assinatura.
    out = ws.edit_file("calc.py", "def soma(a,b):\n    return a+b", "def soma(a, b):\n    return a + b + 0")
    assert "não encontrado" in out
    assert "PARECIDO" in out
    assert "def soma(a, b):" in out          # mostra o texto REAL do arquivo
    assert "linha ~1" in out


def test_edit_sem_dica_quando_nada_parecido(ws):
    ws.write_file("calc.py", "x = 1\ny = 2\n")
    out = ws.edit_file("calc.py", "class TotalmenteDiferente(Enum):", "z")
    assert "não encontrado" in out
    assert "PARECIDO" not in out


def test_edit_exato_continua_funcionando(ws):
    ws.write_file("calc.py", "def soma(a, b):\n    return a - b\n")
    out = ws.edit_file("calc.py", "return a - b", "return a + b")
    assert out.startswith("OK")
    assert "return a + b" in ws.current_content("calc.py")


# ── Commit assistido (git_commit_all) ─────────────────────────────
def _git_ws(tmp_path):
    import subprocess
    ws = CoderWorkspace(str(tmp_path))
    run = lambda *a: subprocess.run(["git", *a], cwd=str(tmp_path),
                                    capture_output=True, text=True)
    run("init")
    run("config", "user.email", "apolo@test.local")
    run("config", "user.name", "Apolo Test")
    return ws


def test_git_commit_all(tmp_path):
    ws = _git_ws(tmp_path)
    ws.write_file("novo.py", "x = 1\n")
    res = ws.git_commit_all("feat: arquivo novo de teste")
    assert res["ok"] is True
    assert res["message"] == "feat: arquivo novo de teste"
    assert ws.git_status()["dirty"] is False   # workspace limpo após o commit


def test_git_commit_sem_mudancas(tmp_path):
    ws = _git_ws(tmp_path)
    ws.write_file("a.py", "x = 1\n")
    ws.git_commit_all("feat: inicial")
    res = ws.git_commit_all("feat: nada")
    assert res["ok"] is False and "nada para commitar" in res["error"]


def test_git_commit_fora_de_repo(ws):
    res = ws.git_commit_all("feat: x")
    assert res["ok"] is False and "repositório" in res["error"]


def test_git_commit_confinado_ao_workspace(tmp_path):
    """REGRESSÃO REAL: com o workspace num SUBDIRETÓRIO de um repo maior,
    o commit assistido varria o repo inteiro (git add -A sem pathspec) —
    chegou a commitar data/ e .claude/ do projeto. Agora tudo é confinado
    ao workspace via pathspec '.'."""
    import subprocess
    run = lambda *a: subprocess.run(["git", *a], cwd=str(tmp_path),
                                    capture_output=True, text=True)
    run("init")
    run("config", "user.email", "apolo@test.local")
    run("config", "user.name", "Apolo Test")
    # Arquivo FORA do workspace (na raiz do repo) — não pode ser tocado.
    (tmp_path / "fora_do_workspace.py").write_text("segredo = 1\n", encoding="utf-8")
    sub = tmp_path / "workspace"
    sub.mkdir()
    ws = CoderWorkspace(str(sub))
    ws.write_file("dentro.py", "x = 1\n")

    st = ws.git_status()
    assert "dentro.py" in st["status"]
    assert "fora_do_workspace" not in st["status"]   # status também confinado

    res = ws.git_commit_all("feat: arquivo do workspace")
    assert res["ok"] is True
    # O arquivo de fora continua NÃO commitado (untracked no repo pai).
    out = run("status", "--short").stdout
    assert "fora_do_workspace.py" in out
    assert "dentro.py" not in out
