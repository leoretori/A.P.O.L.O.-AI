"""Retrospectiva do ano (M12, Épico 12.2): narrativa falável determinística +
propostas para o ano 2."""
from src import retrospective as R


def test_year_two_combina_metas_concretas_e_estrategicas():
    # métrica ruim (alucinação) → meta concreta entra na frente dos temas fixos
    themes = R.year_two_themes({"hallucination_rate": 0.4})
    assert any("alucina" in t.lower() for t in themes)
    assert any(t in R.STRATEGIC_THEMES for t in themes)   # e os estratégicos também


def test_year_two_so_estrategicos_quando_saudavel():
    themes = R.year_two_themes({})
    assert themes[:len(R.STRATEGIC_THEMES)] == R.STRATEGIC_THEMES[:len(themes)]


def test_texto_menciona_numeros_do_ano():
    data = {
        "total_topics": 628, "active_days": 40,
        "coder": {"total": 30, "success_rate": 80},
        "eval": {"score": 0.85, "hallucination_rate": 0.1},
        "feedback": {"up": 12, "down": 3},
        "projects_done": 2,
        "year_two_themes": ["mais agência"],
    }
    txt = R.compose_retrospective_text(data)
    assert "628 tópicos" in txt and "40 dias" in txt
    assert "30 tarefas" in txt and "80%" in txt
    assert "85%" in txt and "10% de alucinação" in txt
    assert "2 projetos de melhoria" in txt
    assert "mais agência" in txt and txt.endswith("Seguimos juntos.")


def test_texto_ano_vazio_ainda_e_falavel():
    txt = R.compose_retrospective_text({})
    assert txt.startswith("Aqui está a retrospectiva") and "Seguimos juntos." in txt


def test_build_retrospective_pacote_completo():
    out = R.build_retrospective(
        {"total_topics": 100, "coder": {"total": 5, "success_rate": 60}},
        {"coder_success": 60})
    assert "highlights" in out and out["highlights"]["total_topics"] == 100
    assert out["year_two_themes"] and isinstance(out["text"], str)
    # o texto deve incorporar os temas do ano 2
    assert "próximo ano" in out["text"]
