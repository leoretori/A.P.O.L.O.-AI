"""Endpoint do A.P.O.L.O. Coder (routers/coder.py) — o último e maior endpoint
extraído do monólito na M1. O parser (parse_coder_action) já é coberto à exaustão
em test_coder_autonomy/test_coder/test_coder_edit; aqui garantimos que a rota foi
registrada e que o parser está acessível pelo novo módulo.
"""
from routers.coder import router, parse_coder_action


def test_rota_registrada():
    assert any(getattr(r, "path", None) == "/api/coder" for r in router.routes)


def test_parser_acessivel_pelo_router():
    # sanity: o parser mora agora em routers.coder e responde às ações básicas
    assert parse_coder_action("LISTAR .")[0] == "list"
    assert parse_coder_action("BUSCAR_WEB: fastapi sse")[0] == "web"
    assert parse_coder_action("CONSULTAR asyncio")[0] == "consult"
    assert parse_coder_action("resposta final sem acao")[0] == "done"
