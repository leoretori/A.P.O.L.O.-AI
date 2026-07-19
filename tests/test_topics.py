"""Testes do universo de estudo e do classificador de setor."""

from src.topics import (
    ALL_SECTORS, ALL_TOPICS, SECTOR_LABELS, TOPIC_SECTOR, VOLATILE_RELEARN_DAYS,
    classify_sector, interleave, is_smalltalk, relearn_window_days,
)


# ── is_smalltalk (evita busca web em saudação) ──────────────────
def test_smalltalk_reconhece_saudacoes():
    for t in ["oi", "Oi!", "olá", "bom dia", "Boa noite!",
              "tudo bem?", "e aí", "valeu", "obrigado", "obrigada", "blz",
              "ok", "tchau", "hey", "hello"]:
        assert is_smalltalk(t), t


def test_smalltalk_ignora_perguntas_reais():
    for t in ["o que é python?", "oi, o que a empresa Avanade faz",
              "me explique async await", "como criar uma LLM do zero",
              "bom dia, preciso de ajuda com FastAPI"]:
        assert not is_smalltalk(t), t


def test_smalltalk_vazio_e_longo():
    assert not is_smalltalk("")
    assert not is_smalltalk("oi " * 20)   # longo demais → não é smalltalk


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


# ── item 2 das melhorias de 2026-07-19: cobertura de setor achada real
# (ACID/BASE caía em "outros" mesmo sendo claramente bancos de dados) ──
def test_classify_acid_transaction_cai_em_databases():
    assert classify_sector("ACID vs BASE consistency models explained") == "databases"


def test_classify_acid_nao_falsopositiva_em_capacidade():
    # "acid" É substring de "capacidade" — por isso o keyword é "acid transaction"/
    # "acid properties" (multi-palavra), nunca "acid" isolado.
    assert classify_sector("capacidade de armazenamento do sistema") == "outros"


# ── cobertura de enciclopédia (achado real 2026-07-19, painel "Mente"):
# centenas de verbetes legítimos ("Metabolismo (enciclopédia)") caiam em
# "outros" só por falta de palavra-chave, não por serem lixo. ──
def test_classify_verbetes_de_enciclopedia_reais():
    assert classify_sector("Metabolismo (enciclopédia)") == "medicine_health"
    assert classify_sector("Grécia Antiga (enciclopédia)") == "history_philosophy"
    assert classify_sector("Via Láctea (enciclopédia)") == "space_astronomy"
    assert classify_sector("Amazônia (enciclopédia)") == "environment_sustainability"
    assert classify_sector("Neurociência (enciclopédia)") == "medicine_health"


def test_classify_nao_falsopositiva_retorica_em_caracteristica():
    # "retórica" foi adicionado como keyword — não deve casar em "característica".
    assert classify_sector("característica marcante do produto") == "outros"


# ── relearn_window_days (P2.7) ───────────────────────────────────
def test_relearn_window_setor_volatil_e_mais_curto():
    dias = relearn_window_days("guia rápido de Kubernetes na AWS", base=21)
    assert dias == VOLATILE_RELEARN_DAYS
    assert dias < 21


def test_relearn_window_setor_estavel_usa_o_base():
    # "física quântica" cai em ciência/setor estável — usa o padrão inteiro.
    dias = relearn_window_days("Introdução à física quântica", base=21)
    assert dias == 21


def test_relearn_window_nao_estoura_acima_do_base():
    """Um base já MENOR que o padrão volátil não deve subir por ser volátil."""
    dias = relearn_window_days("guia rápido de Kubernetes na AWS", base=5)
    assert dias == 5


def test_relearn_window_base_desligado_fica_desligado():
    assert relearn_window_days("guia rápido de Kubernetes na AWS", base=0) == 0
    assert relearn_window_days("Introdução à física quântica", base=-1) == -1
