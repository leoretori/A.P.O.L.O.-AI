"""Avaliação às cegas Nano vs professor (M28) — determinística, sem LLM.

O ponto crítico: o placar tem que mapear a escolha do juiz de volta ao modelo
certo APESAR do embaralhamento A/B. Os fakes fixam isso."""
import json

import pytest

from src.nanollm.blind_eval import (
    _parse_choice,
    append_history,
    blind_compare,
    freeze_questions,
    make_llm_judge,
    read_history,
    run_blind_eval,
    run_tracked_blind_eval,
)


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


# ── Placar histórico rastreável (P1.4) ─────────────────────────────
class _FakeDB:
    def __init__(self, msgs):
        self._msgs = msgs

    def first_user_messages(self, limit=30):
        return self._msgs[:limit]


class _FakeNano:
    def __init__(self, avail=True):
        self._avail = avail

    def available(self):
        return self._avail

    def complete(self, q, max_tokens=80):
        return {"text": "NANO:" + q}


def test_freeze_questions_congela_e_e_idempotente(tmp_path):
    db = _FakeDB([f"pergunta {i}" for i in range(35)])
    path = tmp_path / "q.json"
    qs1 = freeze_questions(db, path, limit=30, min_questions=30)
    assert len(qs1) == 30

    db2 = _FakeDB([f"outra bem diferente {i}" for i in range(35)])
    qs2 = freeze_questions(db2, path, limit=30, min_questions=30)
    assert qs2 == qs1  # não re-sorteou mesmo com o banco tendo mudado


def test_freeze_questions_poucas_perguntas_levanta_erro(tmp_path):
    db = _FakeDB([f"p{i}" for i in range(5)])
    with pytest.raises(ValueError, match="poucas perguntas"):
        freeze_questions(db, tmp_path / "q.json", limit=30, min_questions=30)


def test_append_e_read_history_roundtrip(tmp_path):
    path = tmp_path / "hist.jsonl"
    ok = {"status": "ok", "n": 3, "wins": {"nano": 1, "teacher": 2, "tie": 0},
          "nano_win_rate": 33.3}
    append_history(path, ok, seed=0)
    append_history(path, ok, seed=1)
    hist = read_history(path)
    assert len(hist) == 2
    assert hist[0]["seed"] == 0 and hist[1]["seed"] == 1
    assert all("timestamp" in h for h in hist)


def test_append_history_ignora_status_nao_ok(tmp_path):
    path = tmp_path / "hist.jsonl"
    append_history(path, {"status": "skipped", "reason": "x"}, seed=0)
    assert read_history(path) == []


def test_read_history_arquivo_inexistente(tmp_path):
    assert read_history(tmp_path / "nao_existe.jsonl") == []


def test_run_blind_eval_usa_questions_dado_em_vez_de_reamostrar(monkeypatch):
    chamou_db = {"n": 0}

    class _DBQueSeChamadoFalha:
        def first_user_messages(self, limit=30):
            chamou_db["n"] += 1
            return ["não deveria usar isso"]

    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher",
                        lambda max_tokens=80: (lambda q: "TEACHER"))
    monkeypatch.setattr("src.nanollm.blind_eval.make_llm_judge",
                        lambda: (lambda q, a, b: "A"))
    res = run_blind_eval(_DBQueSeChamadoFalha(), _FakeNano(), questions=["p1", "p2"])
    assert chamou_db["n"] == 0  # não reamostrou
    assert res["n"] == 2


def test_run_tracked_blind_eval_congela_e_registra(tmp_path, monkeypatch):
    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher",
                        lambda max_tokens=80: (lambda q: "TEACHER"))
    monkeypatch.setattr("src.nanollm.blind_eval.make_llm_judge",
                        lambda: (lambda q, a, b: "A"))
    db = _FakeDB([f"pergunta real {i}" for i in range(35)])
    qpath, hpath = tmp_path / "q.json", tmp_path / "h.jsonl"

    res1 = run_tracked_blind_eval(db, _FakeNano(), questions_path=qpath,
                                  history_path=hpath, limit=30, min_questions=30, seed=1)
    assert res1["status"] == "ok" and res1["n"] == 30
    hist = read_history(hpath)
    assert len(hist) == 1 and hist[0]["n"] == 30

    # 2ª rodada usa o MESMO conjunto congelado e acrescenta ao histórico
    res2 = run_tracked_blind_eval(db, _FakeNano(), questions_path=qpath,
                                  history_path=hpath, limit=30, min_questions=30, seed=2)
    assert res2["n"] == 30
    assert len(read_history(hpath)) == 2


def test_run_tracked_blind_eval_pulado_nao_registra(tmp_path, monkeypatch):
    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher",
                        lambda max_tokens=80: (lambda q: "TEACHER"))
    monkeypatch.setattr("src.nanollm.blind_eval.make_llm_judge",
                        lambda: (lambda q, a, b: "A"))
    db = _FakeDB([f"pergunta real {i}" for i in range(35)])
    qpath, hpath = tmp_path / "q.json", tmp_path / "h.jsonl"
    res = run_tracked_blind_eval(db, _FakeNano(avail=False), questions_path=qpath,
                                 history_path=hpath, limit=30, min_questions=30, seed=0)
    assert res["status"] == "skipped"
    assert read_history(hpath) == []


# ── E5: gabarito cacheado, juiz 2× e portão estatístico ──────────────────
def test_cached_teacher_congela_a_referencia(tmp_path):
    """O professor gera com temperatura > 0: sem cache, candidato e titular
    eram comparados contra gabaritos DIFERENTES (E5)."""
    from src.nanollm.blind_eval import cached_teacher

    chamadas = {"n": 0}

    def instavel(q):
        chamadas["n"] += 1
        return f"resposta {chamadas['n']}"

    path = tmp_path / "gabarito.json"
    t = cached_teacher(instavel, path)
    assert t("pergunta A") == "resposta 1"
    assert t("pergunta A") == "resposta 1"      # mesma referência
    assert t("pergunta B") == "resposta 2"
    assert chamadas["n"] == 2

    # persiste entre execuções (outra noite, outro processo)
    t2 = cached_teacher(instavel, path)
    assert t2("pergunta A") == "resposta 1"
    assert chamadas["n"] == 2                   # não chamou o professor de novo


def test_two_pass_transforma_viés_de_posicao_em_empate():
    """Juiz que sempre escolhe 'A' não tem preferência: nas duas ordens ele
    aponta modelos diferentes → inconsistente → empate, não vitória."""
    res = blind_compare([f"p{i}" for i in range(10)], _nano, _teacher,
                        lambda q, a, b: "A", seed=3, two_pass=True)
    assert res["wins"]["tie"] == 10 and res["inconsistentes"] == 10
    assert res["nano_win_rate"] == 0.0


def test_two_pass_mantem_veredito_consistente():
    """Juiz que escolhe pela IDENTIDADE responde igual nas duas ordens."""
    def judge(q, a, b):
        return "A" if a == "RESPOSTA_NANO" else "B"
    res = blind_compare([f"p{i}" for i in range(6)], _nano, _teacher, judge,
                        seed=3, two_pass=True)
    assert res["wins"]["nano"] == 6 and res["inconsistentes"] == 0


def test_paired_win_test_delta_grande_e_significativo():
    from src.nanollm.blind_eval import paired_win_test

    cand = [{"i": i, "winner": "nano" if i < 20 else "teacher"} for i in range(60)]
    base = [{"i": i, "winner": "teacher"} for i in range(60)]
    t = paired_win_test(cand, base)
    assert t["candidato_ganhou"] == 20 and t["titular_ganhou"] == 0
    assert t["p_value"] < 0.001 and t["significativo"] is True


def test_paired_win_test_delta_pequeno_nao_e_significativo():
    """O caso real do E5: candidato 'na frente' por poucas perguntas — que é
    exatamente a oscilação medida no MESMO checkpoint em noites diferentes."""
    from src.nanollm.blind_eval import paired_win_test

    cand = [{"i": i, "winner": "nano" if i < 8 else "teacher"} for i in range(60)]
    base = [{"i": i, "winner": "nano" if 3 <= i < 9 else "teacher"} for i in range(60)]
    t = paired_win_test(cand, base)
    assert t["candidato_ganhou"] == 3 and t["titular_ganhou"] == 1
    assert t["significativo"] is False


def test_paired_win_test_empate_nao_promove():
    from src.nanollm.blind_eval import paired_win_test

    iguais = [{"i": i, "winner": "nano"} for i in range(30)]
    t = paired_win_test(iguais, list(iguais))
    assert t["discordantes"] == 0 and t["significativo"] is False
    assert t["p_value"] == 1.0


def test_freeze_questions_cresce_sem_re_sortear(tmp_path):
    """E5: o conjunto congelado com 15 perguntas (ruído) cresce até o alvo —
    mantendo as antigas, na ordem."""
    path = tmp_path / "q.json"
    db_antigo = _FakeDB([f"antiga {i}" for i in range(15)])
    qs1 = freeze_questions(db_antigo, path, limit=15, min_questions=15)
    assert len(qs1) == 15

    db_maior = _FakeDB([f"antiga {i}" for i in range(15)] +
                       [f"nova {i}" for i in range(60)])
    qs2 = freeze_questions(db_maior, path, limit=60, min_questions=60)
    assert len(qs2) == 60
    assert qs2[:15] == qs1                      # as antigas continuam, na ordem
    assert json.loads(path.read_text(encoding="utf-8")) == qs2
