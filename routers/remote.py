"""Acesso remoto seguro (M11, Épico 11.3): informa como alcançar o A.P.O.L.O. do
celular na mesma rede.

  GET /api/remote/info → {lan_ip, port, url, url_with_token?, auth_required, lan_exposed}

O link `url_with_token` (quando REMOTE_TOKEN está definido) é o que você abre no
celular UMA vez — ele ganha o cookie e não repete o token. Só o dono (localhost)
lê este endpoint com o token embutido.
"""
import os

from fastapi import APIRouter

from src import remote_access

router = APIRouter()


@router.get("/api/remote/info")
async def remote_info():
    host_bind = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    token = os.getenv("REMOTE_TOKEN", "").strip()
    ip = remote_access.lan_ip()
    lan_exposed = host_bind in ("0.0.0.0", "::", "")     # escutando na LAN?
    return {
        "lan_ip": ip,
        "port": port,
        "host_binding": host_bind,
        "lan_exposed": lan_exposed,
        "auth_required": bool(token),
        "url": remote_access.access_url(ip, port),
        "url_with_token": remote_access.url_with_token(ip, port, token) if token else None,
        # dicas honestas do que falta para o acesso funcionar/ser seguro
        "hints": {
            "bind": None if lan_exposed else "defina HOST=0.0.0.0 no .env para escutar na rede local",
            "token": None if token else "defina REMOTE_TOKEN no .env para exigir senha de acesso remoto",
        },
    }
