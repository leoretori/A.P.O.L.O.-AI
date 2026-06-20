"""Testes do universo de estudo e do classificador de setor."""

from src.topics import (
    ALL_SECTORS, ALL_TOPICS, SECTOR_LABELS, TOPIC_SECTOR,
    classify_sector, interleave,
)


def test_todos_topicos_tem_setor_no_mapa_exato():
    # Todo tópico curado deve mapear para seu setor.
    for topic in ALL_TOPICS:
        assert topic in TOPIC_SECTOR


def test_todos_setores_tem_label():
    for sector in ALL_SECTORS:
        assert sector in SECTOR_LABELS
    assert "outros" in SECTOR_LABELS


def test_sem_topicos_duplicados():
    assert len(ALL_TOPICS) == len(set(ALL_TOPICS))


def test_interleave_e_round_robin():
    sectors = {"a": ["a1", "a2"], "b": ["b1", "b2"], "c": ["c1"]}
    # 1º de cada setor, depois 2º de cada (só os que existem).
    assert interleave(sectors) == ["a1", "b1", "c1", "a2", "b2"]


def test_classify_match_exato():
    assert classify_sector("React server components vs client components 2024") == "frontend_web"


def test_classify_por_palavra_chave():
    # Não está no mapa exato — cai no classificador por keyword.
    assert classify_sector("guia rápido de Kubernetes na AWS") == "devops_cloud"
    assert classify_sector("regras de compliance e LGPD na empresa") == "law_compliance"


def test_classify_remove_prefixos():
    assert classify_sector("[A.P.O.L.O.] OWASP Top 10 web vulnerabilities") == "security"
    assert classify_sector("[Tendência] Rust adoption systems programming") == "systems_languages"


def test_classify_desconhecido_vira_outros():
    assert classify_sector("xyzzy plugh blibble") == "outros"
    assert classify_sector("") == "outros"
