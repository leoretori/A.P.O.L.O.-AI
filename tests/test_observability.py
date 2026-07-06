"""Observabilidade (Épico 1.3): logging estruturado + metadados de build."""
import json
import logging

from src.logging_setup import JsonFormatter, configure_logging
from src import build_info


def test_json_formatter_emite_linha_json_com_campos_padrao():
    rec = logging.makeLogRecord({
        "name": "apolo.teste", "levelno": logging.INFO,
        "levelname": "INFO", "msg": "boot ok",
    })
    out = json.loads(JsonFormatter().format(rec))
    assert out["level"] == "INFO"
    assert out["logger"] == "apolo.teste"
    assert out["message"] == "boot ok"
    assert "ts" in out


def test_json_formatter_preserva_campos_extra():
    rec = logging.makeLogRecord({
        "name": "x", "levelname": "INFO", "msg": "evento",
        "event": "boot", "version": "0.1.0",
    })
    out = json.loads(JsonFormatter().format(rec))
    assert out["event"] == "boot" and out["version"] == "0.1.0"


def test_json_formatter_inclui_excecao():
    try:
        raise ValueError("falhou")
    except ValueError:
        import sys
        rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "erro",
                                None, sys.exc_info())
    out = json.loads(JsonFormatter().format(rec))
    assert "ValueError" in out["exc"]


def test_configure_logging_json_ativa_formatter(monkeypatch):
    fmt = configure_logging(level_name="DEBUG", fmt="json")
    assert fmt == "json"
    root = logging.getLogger()
    assert root.level == logging.DEBUG
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
    # Bibliotecas barulhentas seguem silenciadas.
    assert logging.getLogger("httpx").level == logging.WARNING
    configure_logging(level_name="INFO", fmt="text")   # restaura padrão


def test_configure_logging_text_e_o_default():
    fmt = configure_logging(fmt="text")
    assert fmt == "text"
    assert not isinstance(logging.getLogger().handlers[0].formatter, JsonFormatter)


def test_build_info_tem_versao_uptime_e_git():
    info = build_info.build_info()
    assert info["version"]
    assert isinstance(info["uptime_seconds"], int) and info["uptime_seconds"] >= 0
    assert info["git_sha"]  # sha curto ou 'unknown'
    assert info["uptime_human"]


def test_git_sha_respeita_env(monkeypatch):
    build_info.git_sha.cache_clear()
    monkeypatch.setenv("GIT_SHA", "abc123def456789")
    assert build_info.git_sha() == "abc123def456"   # truncado em 12
    build_info.git_sha.cache_clear()


def test_human_uptime_formata_faixas():
    assert build_info._human_uptime(30) == "0m"
    assert build_info._human_uptime(90) == "1m"
    assert build_info._human_uptime(3661) == "1h 1m"
    assert build_info._human_uptime(90061) == "1d 1h 1m"
