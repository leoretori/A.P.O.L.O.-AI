"""Embeddings locais e soberanos (M11, Épico 11.1).

Trava o fallback 100% Python: determinístico, normalizado, e — o que importa —
SEPARA semântica (textos parecidos ficam mais próximos que diferentes). Offline,
sem modelo baixado.
"""
import math

import pytest

from src import embeddings as E


def test_deterministico():
    assert E.hashing_embedding("o mesmo texto") == E.hashing_embedding("o mesmo texto")


def test_normalizado_l2():
    v = E.hashing_embedding("qualquer frase com conteúdo")
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-9
    assert len(v) == E.DEFAULT_DIMS


def test_texto_vazio_vira_vetor_zero():
    assert E.hashing_embedding("") == [0.0] * E.DEFAULT_DIMS


def test_ignora_acento_e_caixa():
    assert E.hashing_embedding("Ação") == E.hashing_embedding("acao")


def test_separa_semantica_parecido_vs_diferente():
    a = E.hashing_embedding("o gato subiu no telhado da casa")
    b = E.hashing_embedding("o gato pulou para o telhado da casa")   # parecido
    c = E.hashing_embedding("política monetária e taxa de juros")     # diferente
    assert E.cosine(a, b) > E.cosine(a, c)


def test_cosine_identico_e_um():
    v = E.hashing_embedding("texto de referência")
    assert abs(E.cosine(v, v) - 1.0) < 1e-6


def test_cosine_dimensoes_diferentes_e_zero():
    assert E.cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_embedding_function_chromadb():
    ef = E.HashingEmbeddingFunction()
    out = ef(["um", "dois"])
    assert len(out) == 2 and len(out[0]) == E.DEFAULT_DIMS
    assert ef.name() == "apolo-hashing"


def test_backend_info_reporta_localidade():
    assert E.backend_info("hashing")["backend"] == "hashing"
    assert E.backend_info("nomic-embed-text")["backend"] == "ollama"
    d = E.backend_info(None)
    assert d["backend"] == "onnx-minilm" and d["local"] is True
    # todos os backends são locais/offline — é o ponto do épico
    for m in ("hashing", "nomic-embed-text", None):
        assert E.backend_info(m)["local"] is True
