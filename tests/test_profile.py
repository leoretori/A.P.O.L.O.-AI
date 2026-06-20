"""Testes da memória pessoal (UserProfile)."""

from src.profile import UserProfile


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
