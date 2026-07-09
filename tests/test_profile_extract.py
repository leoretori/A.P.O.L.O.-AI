"""Extração de candidatos ao modelo (M16.2) + fila pendente do UserProfile."""

from src.profile import UserProfile
from src.profile_extract import extract_candidates


# ------------------------------------------------------------- extrator
def test_extrai_meta():
    c = extract_candidates("minha meta é lançar o Apolo v2 esse ano")
    assert c[0]["category"] == "goal" and "lançar o Apolo v2" in c[0]["text"]


def test_extrai_projeto():
    c = extract_candidates("estou trabalhando no Apolo AI ultimamente")
    assert any(x["category"] == "project" and "Apolo AI" in x["text"] for x in c)


def test_extrai_preferencia():
    c = extract_candidates("prefiro respostas diretas e sem enrolação")
    assert c[0]["category"] == "preference"
    assert c[0]["text"].startswith("respostas diretas")


def test_extrai_valor():
    c = extract_candidates("eu valorizo soberania acima de tudo")
    assert any(x["category"] == "value" for x in c)


def test_extrai_habito():
    c = extract_candidates("todo dia eu estudo IA de manhã")
    assert any(x["category"] == "habit" for x in c)


def test_horizonte_da_meta():
    curto = extract_candidates("quero terminar isso hoje")
    assert curto[0].get("horizon") == "short"
    longo = extract_candidates("meu objetivo é ter uma startup algum dia")
    assert longo[0].get("horizon") == "long"


def test_nao_quero_nao_e_meta():
    c = extract_candidates("não quero trabalhar com isso")
    assert not any(x["category"] == "goal" for x in c)


def test_mensagem_impessoal_nao_extrai():
    assert extract_candidates("qual a capital da França?") == []
    assert extract_candidates("") == []


def test_no_maximo_um_por_categoria():
    c = extract_candidates("prefiro Python e gosto de testes e adoro café")
    prefs = [x for x in c if x["category"] == "preference"]
    assert len(prefs) == 1  # só o primeiro


def test_corta_na_pontuacao():
    c = extract_candidates("prefiro respostas diretas. E odeio rodeios.")
    assert c[0]["text"] == "respostas diretas"


# --------------------------------------------- fila de candidatos (M16.2)
def test_propose_e_pending(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    item = p.propose("respostas diretas", "preference")
    assert item and item["category"] == "preference"
    assert len(p.pending()) == 1
    assert p.list() == []  # NADA foi gravado no perfil


def test_propose_dedup_contra_fato_existente(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.add("uso Python", category="fact")
    assert p.propose("uso Python") is None  # já é fato


def test_propose_dedup_entre_candidatos(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    p.propose("meta X", "goal")
    assert p.propose("META x", "goal") is None  # case-insensitive


def test_confirm_move_para_perfil(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    c = p.propose("terminar o Nano", "goal", horizon="short")
    added = p.confirm(c["id"])
    assert added["fact"] == "terminar o Nano" and added["category"] == "goal"
    assert added["horizon"] == "short" and added["source"] == "user"
    assert p.pending() == [] and len(p.list()) == 1


def test_confirm_com_edicao(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    c = p.propose("apolo ai", "fact")
    added = p.confirm(c["id"], text="Apolo AI (Jarvis)", category="project")
    assert added["fact"] == "Apolo AI (Jarvis)" and added["category"] == "project"


def test_reject_descarta_e_nao_repropoe(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    c = p.propose("algo qualquer", "fact")
    assert p.reject(c["id"]) is True
    assert p.pending() == []
    assert p.propose("algo qualquer", "fact") is None  # recusado não volta


def test_confirm_reject_inexistente(tmp_path):
    p = UserProfile(path=str(tmp_path / "p.json"))
    assert p.confirm("naoexiste") is None
    assert p.reject("naoexiste") is False


def test_candidatos_persistem(tmp_path):
    path = str(tmp_path / "p.json")
    UserProfile(path=path).propose("uma meta", "goal")
    assert len(UserProfile(path=path).pending()) == 1  # recarrega do disco irmão
