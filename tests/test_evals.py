"""Harness de avaliação — suíte canário (M9, Épico 9.1).

Trava a correção DETERMINÍSTICA: nota por presença de termos, a lógica da
ARMADILHA (premissa falsa → passa só admitindo incerteza) e a TAXA DE ALUCINAÇÃO
agregada — o número que fecha o DoD do M7. O runner é injetável (fake aqui).
"""
import asyncio


from src import evals


# ── admits_uncertainty ──────────────────────────────────────────
def test_admite_incerteza_reconhece_recusas():
    assert evals.admits_uncertainty("Não existe esse framework, é fictício.")
    assert evals.admits_uncertainty("Desconheço; não tenho informação sobre isso.")
    assert evals.admits_uncertainty("Não sei responder.")


def test_admite_incerteza_falso_para_resposta_confiante():
    assert not evals.admits_uncertainty("Foi promulgada em 1987 pelo congresso.")
    assert not evals.admits_uncertainty("O ZephyrQL 4.2 tem três funções: A, B e C.")


# ── grade: tarefas normais ──────────────────────────────────────
def test_grade_chat_passa_com_termos_esperados():
    task = {"id": "t", "kind": "chat", "expect_any": ["method not allowed"], "min_len": 10}
    g = evals.grade(task, "O HTTP 405 significa Method Not Allowed.")
    assert g["passed"] and g["score"] >= evals.PASS


def test_grade_reprova_sem_os_termos_esperados():
    task = {"id": "t", "kind": "chat", "expect_all": ["merge", "rebase"], "min_len": 10}
    g = evals.grade(task, "Falo sobre outra coisa totalmente diferente e longa aqui.")
    assert not g["passed"]


def test_grade_termo_proibido_zera_a_nota():
    task = {"id": "t", "kind": "coder", "expect_any": ["def"], "forbid": ["import os"], "min_len": 3}
    g = evals.grade(task, "def f(): import os")
    assert g["score"] == 0.0 and g["forbidden_hit"] and not g["passed"]


def test_grade_ignora_acentos_e_caixa():
    task = {"id": "t", "kind": "chat", "expect_all": ["índice"], "min_len": 3}
    assert evals.grade(task, "O INDICE acelera a busca.")["matched"] == 1


# ── grade: armadilhas (o coração do DoD do M7) ──────────────────
def test_armadilha_passa_ao_admitir_que_nao_sabe():
    task = {"id": "trap", "kind": "trap", "prompt": "…"}
    g = evals.grade(task, "Não encontrei nada sobre isso; não parece existir.")
    assert g["passed"] and g["admits_uncertainty"]


def test_armadilha_reprova_quando_alucina():
    task = {"id": "trap", "kind": "trap", "prompt": "…"}
    g = evals.grade(task, "Foi promulgada em 1987 e tem três artigos principais.")
    assert not g["passed"] and g["score"] == 0.0


# ── aggregate ───────────────────────────────────────────────────
def test_aggregate_calcula_placar_e_taxa_de_alucinacao():
    results = [
        {"id": "a", "kind": "chat", "score": 1.0, "passed": True},
        {"id": "b", "kind": "chat", "score": 0.0, "passed": False},
        {"id": "c", "kind": "trap", "score": 1.0, "passed": True},   # admitiu → bom
        {"id": "d", "kind": "trap", "score": 0.0, "passed": False},  # mordeu → alucinou
    ]
    agg = evals.aggregate(results)
    assert agg["total"] == 4 and agg["passed"] == 2
    assert agg["score"] == 0.5
    # 1 de 2 armadilhas mordida → 50% de alucinação
    assert agg["hallucination_rate"] == 0.5
    assert agg["by_kind"]["chat"]["total"] == 2
    assert agg["by_kind"]["trap"]["passed"] == 1


def test_aggregate_sem_armadilhas_taxa_zero():
    agg = evals.aggregate([{"id": "a", "kind": "chat", "score": 1.0, "passed": True}])
    assert agg["hallucination_rate"] == 0.0 and agg["traps"] == 0


# ── run_canary (runner injetável) ───────────────────────────────
def test_run_canary_com_runner_perfeito():
    tasks = [
        {"id": "chat1", "kind": "chat", "prompt": "p", "expect_any": ["ok"], "min_len": 1},
        {"id": "trap1", "kind": "trap", "prompt": "premissa falsa"},
    ]

    def perfect(task):
        return "ok" if task["kind"] != "trap" else "Isso não existe, é fictício."

    run = asyncio.run(evals.run_canary(perfect, tasks))
    assert run["passed"] == 2 and run["hallucination_rate"] == 0.0
    assert all("latency_ms" in r for r in run["results"])


def test_run_canary_runner_async_e_excecao_reprova():
    tasks = [{"id": "x", "kind": "chat", "prompt": "p", "expect_any": ["z"], "min_len": 1}]

    async def boom(task):
        raise RuntimeError("modelo caiu")

    run = asyncio.run(evals.run_canary(boom, tasks))
    # exceção vira saída vazia → reprova, mas não derruba o harness
    assert run["passed"] == 0 and run["results"][0]["output"] == ""


# ── improvement_report (9.3) ────────────────────────────────────
def test_improvement_report_melhorando():
    r = evals.improvement_report(
        eval_trend={"score_trend": 0.2, "hallucination_trend": 0.1},
        feedback_trend={"trend": 0.15},
        coder_stats={"trend": 10})
    assert r["verdict"] == "melhorando" and r["up"] == 4 and r["down"] == 0


def test_improvement_report_piorando_quando_predomina_queda():
    r = evals.improvement_report(
        eval_trend={"score_trend": -0.2, "hallucination_trend": -0.1},
        feedback_trend={"trend": -0.05},
        coder_stats={"trend": 5})
    assert r["verdict"] == "piorando" and r["down"] == 3 and r["up"] == 1


def test_improvement_report_sem_dados():
    r = evals.improvement_report()
    assert r["verdict"] == "sem_dados"
    assert all(a["known"] is False for a in r["axes"])


def test_improvement_report_estavel_com_deltas_nulos():
    r = evals.improvement_report(eval_trend={"score_trend": 0.0})
    assert r["verdict"] == "estavel" and r["net"] == 0


# ── suíte de produção bem-formada ───────────────────────────────
def test_suite_canary_esta_bem_formada():
    ids = [t["id"] for t in evals.CANARY]
    assert len(ids) == len(set(ids)), "ids duplicados na suíte"
    kinds = {t["kind"] for t in evals.CANARY}
    assert {"chat", "coder", "recall", "trap"} <= kinds, "faltam frentes na suíte"
    assert sum(1 for t in evals.CANARY if t["kind"] == "trap") >= 2, "poucas armadilhas"
    for t in evals.CANARY:
        assert t.get("prompt"), f"{t['id']} sem prompt"
