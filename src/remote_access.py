"""Acesso remoto seguro (M11, Épico 11.3) — o Jarvis no seu bolso, na sua rede.

Hoje o app é localhost. Para alcançá-lo do celular é preciso escutar na LAN
(`HOST=0.0.0.0`) — o que exporia TUDO a qualquer um na rede. Este módulo fecha
essa porta: quando `REMOTE_TOKEN` está definido, todo acesso de fora da própria
máquina (não-loopback) precisa do token; o dono, no localhost, continua livre.

O `X-API-Token` que já existia só protegia ESCRITAS via header (inútil para abrir
a UI no navegador do celular). Aqui o gate cobre a UI inteira via cookie, que o
celular ganha uma vez ao abrir o link `http://<ip-da-lan>:<porta>/?token=…`.

Núcleo DETERMINÍSTICO e testável: `authorize()` decide sem I/O; a descoberta de IP
e o middleware são cascas finas. O túnel HTTPS para fora da LAN é 🔒 setup do Leo
(ex.: reverse tunnel) — documentado, não embutido.
"""
from __future__ import annotations

import hmac
import socket

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "", "testclient"}
COOKIE_NAME = "apolo_remote"


def is_loopback(host: str) -> bool:
    """O cliente é a própria máquina do dono? (localhost passa sem token.)
    'testclient' (TestClient) conta como loopback para os testes locais."""
    h = (host or "").strip().lower()
    return h in _LOOPBACK or h.startswith("127.")


def token_matches(provided: str, expected: str) -> bool:
    """Comparação em tempo constante (evita timing attack). Expected vazio = nunca."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def authorize(client_host: str, expected_token: str, provided_token: str) -> dict:
    """Decide o acesso. Sem token configurado → tudo passa (comportamento atual).
    Loopback → passa (dono). Senão exige o token. → {allowed, reason}."""
    if not expected_token:
        return {"allowed": True, "reason": "gate_off"}
    if is_loopback(client_host):
        return {"allowed": True, "reason": "loopback"}
    if token_matches(provided_token, expected_token):
        return {"allowed": True, "reason": "token"}
    return {"allowed": False, "reason": "no_token"}


def lan_ip() -> str:
    """Melhor palpite do IPv4 desta máquina na LAN (para montar o link do celular).
    Truque do socket UDP: 'conectar' a um IP externo revela a interface de saída —
    nenhum pacote é enviado. Fallback: 127.0.0.1."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        s.close()


def access_url(ip: str, port: int, scheme: str = "http") -> str:
    return f"{scheme}://{ip}:{port}"


def url_with_token(ip: str, port: int, token: str, scheme: str = "http") -> str:
    base = access_url(ip, port, scheme)
    return f"{base}/?token={token}" if token else base
