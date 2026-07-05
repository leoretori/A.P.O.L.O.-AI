"""Router de assets da PWA (routers/assets.py) — primeiro router extraído do
monólito app.py na M1 do JARVIS_ROADMAP. Trava o comportamento das rotas de
raiz (service worker, manifest, ícones) para que a modularização não regrida.

Primeiro teste de integração com TestClient do projeto. Sem `with` (context
manager) → não dispara o lifespan/startup pesado; só exercita o roteamento.
"""
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_sw_js_servido_da_raiz_com_no_store():
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    # Escopo máximo do SW depende de vir da raiz; no-store evita cache do próprio SW.
    assert r.headers["cache-control"] == "no-store, max-age=0"


def test_manifest_servido_da_raiz():
    r = client.get("/manifest.json")
    assert r.status_code == 200


def test_icone_svg():
    r = client.get("/apolo-icon.svg")
    assert r.status_code == 200
    assert "svg" in r.headers["content-type"]


def test_icones_png_caem_no_svg_quando_ausentes():
    # Se o PNG não existe, o fallback é o SVG (ambos devem responder 200).
    for path in ("/apolo-icon-192.png", "/apolo-icon-512.png"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"] in ("image/png", "image/svg+xml")


def test_router_de_assets_registra_as_rotas_esperadas():
    from routers.assets import router
    paths = {route.path for route in router.routes}
    assert {"/sw.js", "/manifest.json", "/apolo-icon.svg",
            "/apolo-icon-192.png", "/apolo-icon-512.png"} <= paths
