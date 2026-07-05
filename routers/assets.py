"""Assets da PWA — service worker, manifest e ícones.

Servidos da RAIZ (não de /static) de propósito: o service worker precisa de
escopo máximo (toda a app). Se viesse de /static/sw.js, o escopo ficaria preso
a /static/ e o cache das páginas quebraria.

Primeiro router extraído de app.py (M1 do JARVIS_ROADMAP). Sem estado global —
por isso foi o candidato mais seguro para estabelecer o padrão de extração.
"""
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/sw.js")
async def pwa_sw():
    return FileResponse(
        "static/sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@router.get("/manifest.json")
async def pwa_manifest():
    return FileResponse(
        "static/manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/apolo-icon.svg")
async def pwa_icon_svg():
    return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")


@router.get("/apolo-icon-192.png")
async def pwa_icon_192():
    path = "static/apolo-icon-192.png"
    if not os.path.exists(path):
        return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")
    return FileResponse(path, media_type="image/png")


@router.get("/apolo-icon-512.png")
async def pwa_icon_512():
    path = "static/apolo-icon-512.png"
    if not os.path.exists(path):
        return FileResponse("static/apolo-icon.svg", media_type="image/svg+xml")
    return FileResponse(path, media_type="image/png")
