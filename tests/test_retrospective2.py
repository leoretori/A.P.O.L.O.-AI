"""Retrospectiva do Ano 2 (M24, Épico 24.3): narrativa falável determinística
com números reais do ano + proposta ancorada do Ano 3."""
from src import retrospective2 as R2


def test_year3_themes_ancorados_no_roadmap():
    themes = R2.year3_themes()
    assert themes == R2.YEAR_THREE_THEMES
    assert any("cobertura" in t.lower() for t in themes)
    assert any("gpu" in t.lower() for t in themes)


def test_year3_themes_respeita_limit():
    assert len(R2.year3_themes(limit=2)) == 2


def test_texto_menciona_numeros_do_ano():
    data = {
        "total_topics": 900, "active_days": 60,
        "nano": {"nano": 30, "teacher": 70, "total": 100, "pct": 30.0},
        "blind_eval": {"n": 10, "win_rate": 40.0},
        "projects_measured": {"total": 4, "improved": 3},
        "eval": {"score": 0.9, "hallucination_rate": 0.05},
        "feedback": {"up": 20, "down": 2},
        "vision_shipped": True,
        "year3_themes": ["crescer a cobertura"],
    }
    txt = R2.compose_retrospective2_text(data)
    assert "900 tópicos" in txt and "60 dias" in txt
    assert "30.0%" in txt      # cobertura do Nano
    assert "40.0% de 10 perguntas" in txt   # blind eval
    assert "4 projetos de melhoria" in txt and "3 melhoraram" in txt
    assert "90%" in txt and "5% de alucinação" in txt
    assert "ver: tela, documentos e câmera" in txt
    assert "crescer a cobertura" in txt
    assert txt.endswith("Seguimos juntos.")


def test_texto_ano_vazio_ainda_e_falavel():
    txt = R2.compose_retrospective2_text({})
    assert txt.startswith("Aqui está a retrospectiva do nosso segundo ano")
    assert txt.endswith("Seguimos juntos.")


def test_texto_um_projeto_melhorou_singular():
    data = {"projects_measured": {"total": 1, "improved": 1}}
    txt = R2.compose_retrospective2_text(data)
    assert "1 projeto de melhoria" in txt and "1 melhorou" in txt


def test_build_retrospective2_pacote_completo():
    out = R2.build_retrospective2({"total_topics": 500,
                                   "nano": {"total": 10, "pct": 20.0}})
    assert "highlights" in out and out["highlights"]["total_topics"] == 500
    assert out["year3_themes"] == R2.YEAR_THREE_THEMES
    assert "Ano 3" in out["text"]
