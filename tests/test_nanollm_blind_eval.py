"""Avaliação às cegas Nano vs professor (M28) — determinística, sem LLM.

O ponto crítico: o placar tem que mapear a escolha do juiz de volta ao modelo
certo APESAR do embaralhamento A/B. Os fakes fixam isso."""
from src.nanollm.blind_eval import _parse_choice, blind_compare, make_llm_judge


def _nano(q):
    return "RESPOSTA_NANO"


def _teacher(q):
    return "RESPOSTA_PROFESSOR"


def test_juiz_que_sempre_prefere_o_nano_da_100pct():
    # o juiz recebe (q, primeira, segunda) já embaralhadas; escolhe pela IDENTIDADE
    def judge(q, a, b):
        return "A" if a == "RESPOSTA_NANO" else "B"
    res = blind_compare(["p1", "p2", "p3", "p4"], _nano, _teacher, judge, seed=1)
    assert res["wins"]["nano"] == 4 and res["nano_win_rate"] == 100.0


def test_juiz_que_sempre_prefere_o_professor_da_0pct():
    def judge(q, a, b):
        return "A" if a == "RESPOSTA_PROFESSOR" else "B"
    res = blind_compare(["p1", "p2", "p3"], _nano, _teacher, judge, seed=1)
    assert res["wins"]["teacher"] == 3 and res["nano_win_rate"] == 0.0


def test_embaralhamento_realmente_troca_a_posicao():
    # com semente fixa, o Nano aparece em A e em B ao longo das rodadas
    res = blind_compare([f"p{i}" for i in range(20)], _nano, _teacher,
                        lambda q, a, b: "A", seed=7)
    posicoes = {r["nano_was"] for r in res["rounds"]}
    assert posicoes == {"A", "B"}               # não ficou preso numa posição


def test_juiz_indeciso_vira_empate():
    res = blind_compare(["p1", "p2"], _nano, _teacher, lambda q, a, b: "sei lá", seed=0)
    assert res["wins"]["tie"] == 2 and res["nano_win_rate"] == 0.0


def test_parse_choice():
    assert _parse_choice("A") == "A"
    assert _parse_choice("  resposta: B melhor") == "B"   # 1ª letra A/B encontrada
    assert _parse_choice("nenhuma") is None


def test_make_llm_judge_usa_provider(monkeypatch):
    class _Prov:
        def list_models(self):
            return ["apolo"]

        def complete(self, model, messages, options=None):
            return "A"
    monkeypatch.setattr("src.providers.get_provider", lambda: _Prov())
    judge = make_llm_judge(model="apolo")
    assert judge("pergunta", "resp A", "resp B") == "A"


def test_make_llm_judge_cede_gpu_ao_usuario_antes_do_veredito(monkeypatch):
    """A avaliação às cegas roda em thread de fundo — o juiz tem que ceder o
    GpuGate antes de cada veredito, senão segura o lock do motor e faz o chat do
    usuário esperar atrás da avaliação (mesma disciplina do teacher_fn)."""
    class _Prov:
        def list_models(self):
            return ["apolo"]

        def complete(self, model, messages, options=None):
            return "A"
    monkeypatch.setattr("src.providers.get_provider", lambda: _Prov())

    calls = {"n": 0}

    class _FakeGate:
        def wait_for_idle_sync(self, *a, **k):
            calls["n"] += 1

    import src.runtime as rt
    monkeypatch.setattr(rt, "gpu_gate", _FakeGate())
    judge = make_llm_judge(model="apolo")
    judge("pergunta", "resp A", "resp B")
    judge("outra", "x", "y")
    assert calls["n"] == 2
