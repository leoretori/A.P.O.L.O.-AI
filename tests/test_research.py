"""Testes do parser de sub-perguntas da Pesquisa Profunda."""

from src.research import (
    _parse_subquestions, _decide_n, _worth_saving, _simplify_query, _build_dossier,
    _parse_refinement,
    MIN_SUBQUESTIONS, MAX_SUBQUESTIONS, MAX_SUBQUESTIONS_HARD,
)


def test_dash_bullets():
    text = "- O que é o protocolo X?\n- Como configurar Y no ambiente Z?\n- Quais os trade-offs?"
    r = _parse_subquestions(text, 3)
    assert len(r) == 3
    assert r[0] == "O que é o protocolo X?"


def test_numbered_lists():
    text = "1. Primeira pergunta investigativa longa\n2) Segunda pergunta investigativa longa"
    assert len(_parse_subquestions(text, 5)) == 2


def test_ignores_short_and_prose():
    text = "Introdução em prosa que não é bullet\n- curta\n- Esta é uma pergunta válida e longa"
    assert _parse_subquestions(text, 5) == ["Esta é uma pergunta válida e longa"]


def test_respects_limit():
    text = "\n".join(f"- pergunta investigativa número {i}" for i in range(10))
    assert len(_parse_subquestions(text, 3)) == 3


def test_dedup_case_insensitive():
    text = "- mesma pergunta repetida aqui\n- Mesma Pergunta Repetida Aqui"
    assert len(_parse_subquestions(text, 5)) == 1


# ── Nº de frentes adaptativo ──────────────────────────────────
def test_decide_n_pergunta_simples_e_curta():
    assert _decide_n("o que é REST?") == MIN_SUBQUESTIONS


def test_decide_n_pergunta_complexa():
    q = "Compare a arquitetura de microsserviços vs monolito, com trade-offs e estratégia de migração"
    assert _decide_n(q) == MAX_SUBQUESTIONS_HARD


def test_decide_n_pergunta_longa():
    assert _decide_n("x " * 120) == MAX_SUBQUESTIONS_HARD


def test_decide_n_media_usa_padrao():
    # >60 chars, sem 2+ pistas de complexidade → usa o padrão.
    q = "Como configurar autenticação JWT com refresh tokens numa API FastAPI usando Postgres?"
    assert _decide_n(q) == MAX_SUBQUESTIONS


def test_persist_findings_salva_nos_dois_stores():
    from src.research import DeepResearchAgent
    saved_k, saved_r = [], []

    class FakeK:
        def save(self, title, url, content, category, tags):
            saved_k.append({"title": title, "url": url, "category": category, "tags": tags})

    class FakeR:
        def add_example(self, content, doc_id):
            saved_r.append({"content": content, "doc_id": doc_id})

    agent = DeepResearchAgent(model="m", rag=FakeR(), knowledge_db=FakeK())
    agent._persist_findings("O que é RAG e como aplicar?", "resposta densa " * 40,
                            [{"n": 1, "url": "http://x"}])
    assert len(saved_k) == 1 and saved_k[0]["category"] == "deep_research"
    assert saved_k[0]["url"].startswith("research://apolo/")
    assert len(saved_r) == 1 and saved_r[0]["doc_id"].startswith("research_")


# ── Guarda de persistência ────────────────────────────────────
def test_worth_saving():
    assert _worth_saving("a" * 500, [{"n": 1}]) is True
    assert _worth_saving("a" * 500, []) is False        # sem fontes → não salva
    assert _worth_saving("curto", [{"n": 1}]) is False  # raso → não salva
    assert _worth_saving("", [{"n": 1}]) is False


# ── 2º round: simplificação de query ──────────────────────────
def test_simplify_query_extrai_nucleo():
    s = _simplify_query("Como funciona o protocolo OAuth2 em APIs REST modernas?")
    # mantém termos significativos, sem stopwords, na ordem de aparição
    assert "funciona" in s and "oauth2" in s and "rest" in s
    assert "como" not in s.split() and "em" not in s.split()
    assert len(s.split()) <= 6


def test_simplify_query_limita_seis_termos():
    s = _simplify_query("alpha beta gamma delta epsilon zeta eta theta iota")
    assert len(s.split()) == 6


# ── 2º round: parsing do refino ───────────────────────────────
def test_refine_completo_nao_acrescenta():
    assert _parse_refinement("COMPLETO") == ""
    assert _parse_refinement("completo, está ótimo") == ""
    assert _parse_refinement("") == ""


def test_refine_com_cabecalho():
    out = _parse_refinement("## Complemento\nFalta mencionar o trade-off de latência em sistemas distribuídos.")
    assert out.startswith("## Complemento")
    assert "latência" in out


def test_refine_remove_scaffolding_antes_do_cabecalho():
    txt = "Aqui está o que falta:\n## Complemento\nConsiderar também o custo de manutenção e observabilidade."
    out = _parse_refinement(txt)
    assert out.startswith("## Complemento")


def test_refine_sem_cabecalho_curto_ignora():
    assert _parse_refinement("faltou X") == ""  # curto demais → descarta ruído


def test_refine_sem_cabecalho_substancial_adiciona_titulo():
    longo = "Seria importante abordar também a estratégia de cache e o impacto em escalabilidade horizontal do sistema."
    out = _parse_refinement(longo)
    assert out.startswith("## Complemento")
    assert "cache" in out


# ── Dossiê inclui o trecho da fonte web ───────────────────────
def test_dossie_inclui_snippet_web():
    results = [{
        "subq": "o que é gRPC?",
        "memories": [],
        "web_sources": [{"title": "gRPC docs", "url": "http://x", "snippet": "gRPC é um framework RPC de alto desempenho"}],
        "web_context": "",
    }]
    dossier, sources = _build_dossier(results)
    assert "gRPC docs" in dossier
    assert "framework RPC de alto desempenho" in dossier  # snippet entrou no dossiê
    assert sources[0]["url"] == "http://x"
