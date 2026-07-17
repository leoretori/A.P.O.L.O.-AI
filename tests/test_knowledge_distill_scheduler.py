"""Destilação de conhecimento noturna (item 1 do PLANO_FLYWHEEL_AUTOMATICO.md)
— regenera o corpus de Q&A ancorado a partir do learned_topics mais recente,
sem depender de CLI manual. Mesmo padrão do flywheel/dedup/qualidade."""

import asyncio
from pathlib import Path

import app as app_module


class _FakeDB:
    pass


def test_run_knowledge_distill_cycle_sem_db_nao_levanta():
    app_module.db = None
    asyncio.run(app_module._run_knowledge_distill_cycle())  # não levanta


def test_run_knowledge_distill_cycle_sem_tokenizer_pula(monkeypatch, tmp_path):
    app_module.db = _FakeDB()
    monkeypatch.setenv("NANO_CKPT", str(tmp_path / "nao_existe"))
    asyncio.run(app_module._run_knowledge_distill_cycle())  # não levanta, só loga e pula


def test_run_knowledge_distill_cycle_chama_run_knowledge_distillation(monkeypatch, tmp_path):
    ckpt = tmp_path / "ckpt_v1"
    ckpt.mkdir()
    (ckpt / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NANO_CKPT", str(ckpt))
    app_module.db = _FakeDB()

    calls = {}

    def fake_teacher(*a, **k):
        return lambda p: "resposta"

    def fake_run_knowledge_distillation(db, tokenizer_path, out_dir, *, teacher_fn,
                                        limit, max_per_sector):
        calls["tokenizer_path"] = Path(tokenizer_path)
        calls["out_dir"] = out_dir
        calls["limit"] = limit
        calls["max_per_sector"] = max_per_sector
        return {"pairs": 42}

    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher", fake_teacher)
    monkeypatch.setattr("src.nanollm.distill.run_knowledge_distillation",
                        fake_run_knowledge_distillation)

    asyncio.run(app_module._run_knowledge_distill_cycle())
    assert calls["tokenizer_path"] == ckpt / "tokenizer.json"
    assert calls["max_per_sector"] == app_module.KNOWLEDGE_DISTILL_MAX_PER_SECTOR


def test_run_knowledge_distill_cycle_erro_nao_derruba_scheduler(monkeypatch, tmp_path):
    ckpt = tmp_path / "ckpt_v1"
    ckpt.mkdir()
    (ckpt / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NANO_CKPT", str(ckpt))
    app_module.db = _FakeDB()

    def _raise(*a, **k):
        raise RuntimeError("professor fora do ar")

    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher", _raise)
    asyncio.run(app_module._run_knowledge_distill_cycle())  # não levanta


def test_run_knowledge_distill_cycle_sem_pares_pula(monkeypatch, tmp_path):
    """run_knowledge_distillation levanta ValueError quando não há pares
    aproveitáveis — o ciclo trata isso como 'pulado', não como falha."""
    ckpt = tmp_path / "ckpt_v1"
    ckpt.mkdir()
    (ckpt / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NANO_CKPT", str(ckpt))
    app_module.db = _FakeDB()

    def fake_teacher(*a, **k):
        return lambda p: "resposta"

    def _raise_value_error(*a, **k):
        raise ValueError("sem sínteses aproveitáveis")

    monkeypatch.setattr("src.nanollm.distill.make_llm_teacher", fake_teacher)
    monkeypatch.setattr("src.nanollm.distill.run_knowledge_distillation", _raise_value_error)
    asyncio.run(app_module._run_knowledge_distill_cycle())  # não levanta
