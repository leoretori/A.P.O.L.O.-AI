"""NanoEngine + router /api/nano (Épico 3.2): a LLM própria servindo o app."""

import json

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.nano import router
from src import runtime as rt
from src.nanollm.engine import NanoEngine
from src.nanollm.model import GPT, GPTConfig
from src.nanollm.tokenizer import ByteBPETokenizer


@pytest.fixture()
def ckpt(tmp_path):
    tok = ByteBPETokenizer()
    tok.train("O Apolo aprende sozinho todos os dias. " * 40, vocab_size=300)
    model = GPT(GPTConfig(vocab_size=tok.vocab_size, block_size=32, n_layer=1,
                          n_head=2, n_embd=16, seed=1))
    ck = tmp_path / "ckpt"
    ck.mkdir()
    model.save(ck / "model_best.npz")
    tok.save(ck / "tokenizer.json")
    (ck / "eval_report.json").write_text(
        json.dumps({"val": {"ppl": 158.0}, "passo_treino": 5000}), encoding="utf-8")
    return ck


@pytest.fixture()
def client(ckpt, monkeypatch):
    engine = NanoEngine(ckpt)
    monkeypatch.setattr(rt, "nano", engine)
    monkeypatch.setattr(rt, "gpu_gate", None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ------------------------------------------------------------------- engine
def test_engine_lazy_e_info(ckpt):
    e = NanoEngine(ckpt)
    assert e.available() and not e.is_ready()  # existe, mas não carregou
    info = e.info()
    assert info["available"] and info["val_ppl"] == 158.0
    r = e.complete("O Apolo", max_tokens=8, seed=1)
    assert e.is_ready()  # carregou na 1ª completion
    assert r["tokens"] >= 1 and isinstance(r["text"], str) and r["ms"] >= 0
    assert e.info()["params_m"] == r["params_m"]


def test_engine_deterministico_com_seed(ckpt):
    e = NanoEngine(ckpt)
    a = e.complete("O Apolo", max_tokens=8, seed=7)
    b = e.complete("O Apolo", max_tokens=8, seed=7)
    assert a["text"] == b["text"]


def test_engine_sem_checkpoint(tmp_path):
    e = NanoEngine(tmp_path / "vazio")
    assert not e.available()
    with pytest.raises(FileNotFoundError):
        e.complete("oi")


def test_engine_prompt_vazio(ckpt):
    with pytest.raises(ValueError):
        NanoEngine(ckpt).complete("   ")


def test_engine_serializa_threads(ckpt):
    """Gerações concorrentes não podem corromper os caches internos."""
    import threading

    e = NanoEngine(ckpt)
    esperado = e.complete("O Apolo", max_tokens=6, seed=3)["text"]
    resultados: list[str] = []

    def gera():
        resultados.append(e.complete("O Apolo", max_tokens=6, seed=3)["text"])

    threads = [threading.Thread(target=gera) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert resultados == [esperado] * 4


# ------------------------------------------------------------------- router
def test_status_endpoint(client):
    r = client.get("/api/nano/status")
    assert r.status_code == 200
    assert r.json()["available"] is True


def test_complete_endpoint(client):
    r = client.post("/api/nano/complete",
                    json={"prompt": "O Apolo", "max_tokens": 8, "seed": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "apolo-nano" and body["soberano"] is True
    assert body["tokens"] >= 1


def test_complete_503_sem_engine(monkeypatch):
    monkeypatch.setattr(rt, "nano", None)
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/api/nano/complete", json={"prompt": "oi"})
    assert r.status_code == 503


def test_complete_valida_entrada(client):
    assert client.post("/api/nano/complete", json={"prompt": ""}).status_code == 422
    assert client.post("/api/nano/complete",
                       json={"prompt": "oi", "max_tokens": 9999}).status_code == 422


def test_complete_marca_gpu_gate(ckpt, monkeypatch):
    """A completion do Nano conta como atividade de usuário no gate."""
    eventos: list[str] = []

    class FakeGate:
        def user_enter(self):
            eventos.append("enter")

        def user_exit(self):
            eventos.append("exit")

    monkeypatch.setattr(rt, "nano", NanoEngine(ckpt))
    monkeypatch.setattr(rt, "gpu_gate", FakeGate())
    app = FastAPI()
    app.include_router(router)
    r = TestClient(app).post("/api/nano/complete",
                             json={"prompt": "O Apolo", "max_tokens": 4})
    assert r.status_code == 200
    assert eventos == ["enter", "exit"]


def test_engine_respeita_env(tmp_path, monkeypatch):
    monkeypatch.setenv("NANO_CKPT", str(tmp_path / "meu_ckpt"))
    e = NanoEngine()
    assert str(tmp_path / "meu_ckpt") in str(e.ckpt_dir)


def test_generate_fast_respeita_dtype_do_idx(ckpt):
    """Sanidade: o fluxo do engine usa int64 e o modelo devolve ids válidos."""
    e = NanoEngine(ckpt)
    r = e.complete("Apolo aprende", max_tokens=12, seed=2)
    ids = e._tok.encode(r["text"])
    assert all(0 <= i < e._model.config.vocab_size for i in np.array(ids))
