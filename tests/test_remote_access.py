"""Acesso remoto seguro (M11, Épico 11.3).

Trava o gate de autorização: sem token → tudo passa (comportamento atual);
loopback (dono) sempre passa; de fora exige o token certo (comparação constante).
"""
import pytest

from src import remote_access as R


# ── is_loopback ─────────────────────────────────────────────────
def test_loopback_reconhece_localhost():
    for h in ("127.0.0.1", "::1", "localhost", "testclient", "127.0.0.5", ""):
        assert R.is_loopback(h) is True


def test_loopback_falso_para_ip_de_rede():
    assert R.is_loopback("192.168.0.42") is False
    assert R.is_loopback("10.0.0.3") is False


# ── token_matches (tempo constante) ─────────────────────────────
def test_token_matches():
    assert R.token_matches("segredo", "segredo") is True
    assert R.token_matches("errado", "segredo") is False
    assert R.token_matches("", "segredo") is False
    assert R.token_matches("x", "") is False           # sem expected, nunca casa


# ── authorize (núcleo da decisão) ───────────────────────────────
def test_gate_desligado_libera_tudo():
    d = R.authorize("192.168.0.9", expected_token="", provided_token="")
    assert d["allowed"] and d["reason"] == "gate_off"


def test_dono_no_localhost_passa_sem_token():
    d = R.authorize("127.0.0.1", expected_token="s3nha", provided_token="")
    assert d["allowed"] and d["reason"] == "loopback"


def test_de_fora_com_token_certo_passa():
    d = R.authorize("192.168.0.9", expected_token="s3nha", provided_token="s3nha")
    assert d["allowed"] and d["reason"] == "token"


def test_de_fora_sem_token_e_bloqueado():
    d = R.authorize("192.168.0.9", expected_token="s3nha", provided_token="")
    assert d["allowed"] is False and d["reason"] == "no_token"


def test_de_fora_com_token_errado_e_bloqueado():
    d = R.authorize("192.168.0.9", expected_token="s3nha", provided_token="chute")
    assert d["allowed"] is False


# ── URLs ────────────────────────────────────────────────────────
def test_urls():
    assert R.access_url("192.168.0.9", 8000) == "http://192.168.0.9:8000"
    assert R.url_with_token("192.168.0.9", 8000, "abc") == "http://192.168.0.9:8000/?token=abc"
    assert R.url_with_token("192.168.0.9", 8000, "") == "http://192.168.0.9:8000"


def test_lan_ip_retorna_string():
    ip = R.lan_ip()
    assert isinstance(ip, str) and ip.count(".") == 3   # IPv4 plausível
