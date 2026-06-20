"""Testes dos helpers do Modo Agente (parsing de ação + limpeza de resposta)."""

from app import _clean_agent_answer, _parse_agent_action


# ── Limpeza de scaffolding vazado por modelos leves ───────────
def test_clean_remove_resposta_final_simples():
    assert _clean_agent_answer("RESPOSTA FINAL: o valor é 42") == "o valor é 42"


def test_clean_remove_resposta_final_markdown():
    assert _clean_agent_answer("**RESPOSTA FINAL:** média 25.0") == "média 25.0"


def test_clean_remove_respostar_typo():
    assert _clean_agent_answer("RESPOSTAR: Sam Altman") == "Sam Altman"


def test_clean_corta_cauda_de_avaliacao():
    txt = "A média é 15.67.\nAvalie: está correta e completa?"
    assert _clean_agent_answer(txt) == "A média é 15.67."


def test_clean_texto_normal_intacto():
    assert _clean_agent_answer("A resposta é direta e limpa.") == "A resposta é direta e limpa."


# ── Parsing da ação ReAct ─────────────────────────────────────
def test_parse_acao_codigo():
    action, payload = _parse_agent_action("vou calcular\n```python\nprint(2+2)\n```")
    assert action == "code"
    assert "print(2+2)" in payload


def test_parse_acao_buscar_web():
    action, payload = _parse_agent_action("BUSCAR_WEB: CEO atual da OpenAI")
    assert action == "web"
    assert payload == "CEO atual da OpenAI"


def test_parse_acao_consultar_base():
    action, payload = _parse_agent_action("CONSULTAR_BASE: arquitetura hexagonal")
    assert action == "base"
    assert payload == "arquitetura hexagonal"


def test_parse_acao_final():
    action, payload = _parse_agent_action("A resposta é 42.")
    assert action == "final"
    assert payload == "A resposta é 42."


def test_parse_codigo_tem_prioridade_sobre_diretiva():
    # Se houver código, executa o código (ação concreta) mesmo que cite uma diretiva no texto.
    action, _ = _parse_agent_action("BUSCAR_WEB: x\n```python\nprint(1)\n```")
    assert action == "code"
