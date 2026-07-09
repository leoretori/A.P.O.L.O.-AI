"""Testes da memória pessoal (UserProfile) + modelo profundo (M16.1)."""

import json

from src.profile import UserProfile, normalize_category


def test_add_and_list(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("uso FastAPI no trabalho")
    assert item and item["source"] == "user"
    assert len(p.list()) == 1


def test_dedup_case_insensitive(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.add("Projeto Apolo")
    assert p.add("projeto apolo") is None
    assert len(p.list()) == 1


def test_source_auto(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("prefere respostas diretas", source="auto")
    assert item["source"] == "auto"


def test_remove(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("fato qualquer aqui")
    assert p.remove(item["id"]) is True
    assert p.remove("inexistente") is False
    assert p.list() == []


def test_too_short_rejected(tmp_path):
    assert UserProfile(path=str(tmp_path / "p.json")).add("ab") is None


def test_persist_across_instances(tmp_path):
    path = str(tmp_path / "p.json")
    UserProfile(path=path).add("stack Postgres + Redis")
    assert len(UserProfile(path=path).list()) == 1  # recarrega do disco


def test_as_context(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.add("uso Python")
    p.add("gosto de testes")
    ctx = p.as_context()
    assert "- uso Python" in ctx and "- gosto de testes" in ctx


# ---------------------------------------------------- modelo profundo (M16.1)
def test_default_category_e_backcompat(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("uso FastAPI")
    assert item["category"] == "fact"  # sem categoria → default
    assert "created_at" in item


def test_categorias_estruturadas(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.add("lançar o Apolo v2", category="goal", horizon="long")
    p.add("Apolo AI", category="project")
    p.add("acorda 6h e estuda", category="habit")
    groups = p.by_category()
    assert set(groups) == {"goal", "project", "habit"}
    assert groups["goal"][0]["horizon"] == "long"


def test_categoria_invalida_vira_default(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("algo", category="inventada")
    assert item["category"] == "fact"
    assert normalize_category("goal") == "goal"
    assert normalize_category(None) == "fact"


def test_horizonte_so_valido_grava(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("meta", category="goal", horizon="medio")  # inválido
    assert "horizon" not in item


def test_update_edita_entrada(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("uso Postgre", category="fact")
    upd = p.update(item["id"], fact="uso PostgreSQL", category="preference")
    assert upd["fact"] == "uso PostgreSQL" and upd["category"] == "preference"
    assert p.update("inexistente", fact="x") is None
    # persiste
    assert UserProfile(path=p.path).list()[0]["fact"] == "uso PostgreSQL"


def test_update_horizon_remove_com_invalido(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.add("meta", category="goal", horizon="short")
    p.update(item["id"], horizon="lixo")  # inválido → remove o horizonte
    assert "horizon" not in p.list()[0]


def test_as_context_agrupado_por_secao(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.add("terminar o Nano", category="goal", horizon="short")
    p.add("Apolo AI", category="project")
    p.add("prefere respostas diretas", category="preference")
    ctx = p.as_context()
    assert "## Metas" in ctx and "## Projetos ativos" in ctx and "## Preferências" in ctx
    assert "- terminar o Nano (curto prazo)" in ctx
    # ordem: metas antes de projetos antes de preferências
    assert ctx.index("## Metas") < ctx.index("## Projetos ativos") < ctx.index("## Preferências")


def test_as_context_respeita_limite(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    for i in range(10):
        p.add(f"fato numero {i}", category="fact")
    ctx = p.as_context(limit=3)
    assert ctx.count("\n- ") + (1 if ctx.startswith("- ") else 0) <= 3


def test_migracao_perfil_antigo_sem_categoria(tmp_path):
    """Perfil gravado ANTES do M16.1 (entradas sem 'category') carrega como fato."""
    path = tmp_path / "p.json"
    path.write_text(json.dumps([{"id": "f1", "fact": "legado", "source": "user"}]),
                    encoding="utf-8")
    p = UserProfile(path=str(path))
    assert p.list()[0]["category"] == "fact"
    assert "## Sobre você" in p.as_context()


def test_as_context_vazio(tmp_path):
    assert UserProfile(path=str(tmp_path / "p.json")).as_context() == ""
