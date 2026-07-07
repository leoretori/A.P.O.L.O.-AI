"""Grafo de conhecimento — conexões entre tópicos (M8, Épico 8.3).
Fecha o DoD do M8: 'como X se conecta com Y?'.
"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from app import app
from src import graph as G
from src import runtime as rt
from src.learner import LearningEngine
from src.routing import route_task
from src.storage import DatabaseManager

client = TestClient(app)


# ── Núcleo determinístico ─────────────────────────────────────
def test_shared_concepts_e_strength():
    a = "Redis é um banco de dados em memória usado para cache e filas."
    b = "Memcached é um cache em memória; Redis também serve de cache distribuído."
    shared = G.shared_concepts(a, b)
    assert "redis" in shared and "cache" in shared and "memoria" in shared
    assert G.strength(a, b) > 0


def test_explain_direto():
    r = G.explain("Redis", "cache em memoria distribuido",
                  "Memcached", "cache em memoria simples")
    assert r["connected"] and r["kind"] == "direct"
    assert "cache" in r["shared"] and "conectam" in r["answer"]


def test_explain_ponte():
    r = G.explain("A", "xxxx yyyy", "B", "zzzz wwww",
                  bridge=("Ponte", ["xxxx"], ["zzzz"]))
    assert r["connected"] and r["kind"] == "bridge" and r["bridge"] == "Ponte"
    assert "Ponte" in r["answer"]


def test_explain_sem_conexao():
    r = G.explain("A", "alfa beta", "B", "gama delta")
    assert r["connected"] is False and r["kind"] == "none"


def test_parse_connect_question():
    assert G.parse_connect_question("como Redis se conecta com Kafka?") == ("Redis", "Kafka")
    assert G.parse_connect_question("qual a relação entre estoicismo e psicologia") == \
        ("estoicismo", "psicologia")
    assert G.parse_connect_question("o que é fotossíntese") is None


def test_route_connect():
    r = route_task("como redis se conecta com kafka?")
    assert r["route"] == "connect" and r["a"] == "redis" and r["b"] == "kafka"


# ── Storage do grafo ──────────────────────────────────────────
@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/g.db")


def test_edges_upsert_neighbors_canonico(db):
    db.add_edge("Kafka", "Redis", 0.4, ["fila", "cache"])
    db.add_edge("redis", "redis", 0.9, ["x"])       # laço trivial ignorado
    # ordem canônica: buscar por qualquer direção acha
    assert db.get_edge("Redis", "Kafka")["weight"] == 0.4
    nb = db.neighbors("Redis")
    assert nb and nb[0]["topic"] == "Kafka" and "fila" in nb[0]["shared"]
    assert db.count_edges() == 1


def test_find_bridge(db):
    db.add_edge("A", "Meio", 0.5, ["p"])
    db.add_edge("B", "Meio", 0.4, ["q"])
    br = db.find_bridge("A", "B")
    assert br and br["bridge"] == "Meio"
    assert db.find_bridge("A", "Z") is None


# ── Learner: constrói arestas ao aprender ─────────────────────
def test_link_related_cria_arestas(db):
    # tópicos existentes com sobreposição de conceitos
    db.save_learned_topic("Cache distribuído", "u1",
                          "sistemas de cache em memoria distribuido para performance", "web")
    db.save_learned_topic("Culinária", "u2", "receitas de bolo e comida caseira", "web")

    eng = LearningEngine.__new__(LearningEngine)
    eng.db = db

    async def run():
        await eng._link_related("Redis",
                                "redis banco em memoria usado para cache distribuido")
    asyncio.run(run())

    nb = [n["topic"] for n in db.neighbors("Redis")]
    assert "Cache distribuído" in nb        # ligou ao relacionado
    assert "Culinária" not in nb            # não ligou ao não-relacionado


# ── Endpoint ──────────────────────────────────────────────────
def test_endpoint_connect(tmp_path):
    prev = rt.db
    rt.db = DatabaseManager(database_url=f"sqlite:///{tmp_path}/ep.db")
    rt.db.save_learned_topic("Redis", "u", "banco em memoria para cache distribuido", "web")
    rt.db.save_learned_topic("Memcached", "u", "cache em memoria distribuido simples", "web")
    try:
        d = client.get("/api/graph/connect",
                       params={"q": "como Redis se conecta com Memcached?"}).json()
        assert d["ok"] and d["connected"] and "cache" in d["shared"]
    finally:
        rt.db = prev
