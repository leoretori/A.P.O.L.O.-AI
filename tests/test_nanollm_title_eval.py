"""Régua da tarefa de TÍTULO (E6): gate_accept num held-out congelado.

O portão do flywheel passou a decidir por ESTA métrica em vez de perplexidade —
o candidato treina na distribuição do val destilado e quase sempre "ganha" no
ppl, enquanto três experimentos manuais mediram a qualidade real caindo.
"""
import json

import pytest

from src.nanollm.title_eval import freeze_title_messages, title_gate_accept


class _FakeDB:
    def __init__(self, msgs):
        self._msgs = msgs

    def first_user_messages(self, limit=300, min_len=8):
        return self._msgs[:limit]


class _FakeEngine:
    """Motor fake: devolve a completion combinada por mensagem."""

    def __init__(self, respostas, avail=True):
        self._respostas = respostas
        self._avail = avail
        self.seeds = []

    def available(self):
        return self._avail

    def complete(self, prompt, max_tokens=16, temperature=0.5, top_k=20, seed=None):
        self.seeds.append(seed)
        return {"text": self._respostas[len(self.seeds) - 1]}


MSGS = ["Como configurar autenticação JWT no FastAPI",
        "Preciso otimizar uma query lenta no Postgres",
        "Qual a diferença entre asyncio e threading"]


def test_gate_accept_conta_so_titulo_valido_e_relevante(tmp_path):
    """Título bem-formado mas SEM relação com a mensagem não conta — foi o modo
    de falha real do v1 ('AWS S3' para pergunta de asyncio)."""
    engine = _FakeEngine([
        "Autenticação JWT no FastAPI\n",     # ok e relevante
        "AWS S3 e buckets\n",                # bem-formado, mas irrelevante
        "asyncio versus threading\n",        # ok e relevante
    ])
    res = title_gate_accept(tmp_path / "ckpt", MSGS, engine=engine)
    assert res["status"] == "ok"
    assert res["aceitos"] == 2 and res["n"] == 3
    assert res["accept_rate"] == 66.7
    assert [r["ok"] for r in res["rounds"]] == [True, False, True]
    assert [r["i"] for r in res["rounds"]] == [0, 1, 2]   # pareável item a item


def test_gate_accept_rejeita_lixo_degenerado(tmp_path):
    engine = _FakeEngine(["", "## | https://x ##\n", "jwt jwt jwt jwt\n"])
    res = title_gate_accept(tmp_path / "ckpt", MSGS, engine=engine)
    assert res["aceitos"] == 0 and res["accept_rate"] == 0.0


def test_gate_accept_deterministico(tmp_path):
    """Mesma seed por mensagem → mesmo veredito, run a run."""
    def engine():
        return _FakeEngine(["Autenticação JWT no FastAPI\n"] * 3)
    a = title_gate_accept(tmp_path / "ckpt", MSGS, engine=engine())
    e = engine()
    b = title_gate_accept(tmp_path / "ckpt", MSGS, engine=e)
    assert a["rounds"] == b["rounds"]
    assert e.seeds == [0, 1, 2]          # uma seed fixa por posição


def test_gate_accept_sem_checkpoint(tmp_path):
    res = title_gate_accept(tmp_path / "ckpt", MSGS, engine=_FakeEngine([], avail=False))
    assert res["status"] == "skipped"


def test_gate_accept_nao_derruba_com_motor_quebrado(tmp_path):
    class _Quebrado(_FakeEngine):
        def complete(self, *a, **k):
            raise RuntimeError("checkpoint corrompido")

    res = title_gate_accept(tmp_path / "ckpt", MSGS, engine=_Quebrado([]))
    assert res["status"] == "ok" and res["aceitos"] == 0


def test_freeze_title_messages_congela_e_cresce(tmp_path):
    path = tmp_path / "held_out.json"
    db = _FakeDB([f"mensagem real numero {i}" for i in range(30)])

    qs1 = freeze_title_messages(db, path, n=10, min_messages=5)
    assert len(qs1) == 10

    # outro banco, mesmo arquivo → NÃO re-sorteia
    db2 = _FakeDB([f"completamente outra {i}" for i in range(30)])
    assert freeze_title_messages(db2, path, n=10, min_messages=5) == qs1

    # cresce mantendo as antigas na ordem
    qs2 = freeze_title_messages(db, path, n=20, min_messages=5)
    assert len(qs2) == 20 and qs2[:10] == qs1
    assert json.loads(path.read_text(encoding="utf-8")) == qs2


def test_freeze_title_messages_poucas_mensagens(tmp_path):
    db = _FakeDB(["uma só"])
    with pytest.raises(ValueError, match="poucas mensagens"):
        freeze_title_messages(db, tmp_path / "h.json", n=10, min_messages=10)
