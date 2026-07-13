"""Logging à prova de console cp1252 (Windows) — '→'/emoji não podem quebrar.

Regressão real: um log com '→' (U+2192) no /api/ingest levantava UnicodeEncodeError
dentro do handler → 500 na requisição (e derrubava o flywheel). Aqui garantimos
que (a) o stream do handler escreve com errors='replace' e (b) erros de log nunca
propagam (raiseExceptions=False)."""
import io
import logging

from src.logging_setup import _utf8_safe, configure_logging


def test_utf8_safe_nao_quebra_em_stream_cp1252():
    # Simula o console do Windows: TextIOWrapper cp1252 sobre um buffer de bytes.
    raw = io.BytesIO()
    cp = io.TextIOWrapper(raw, encoding="cp1252")
    safe = _utf8_safe(cp)
    safe.write("[ingest] 'cv.pdf' → 6 trechos ☀️")   # '→' e emoji: cp1252 puro estouraria
    safe.flush()
    assert raw.getvalue()                              # escreveu algo, sem exceção


def test_configure_logging_desliga_raise_exceptions():
    configure_logging()
    assert logging.raiseExceptions is False


def test_log_com_seta_nao_propaga_excecao():
    configure_logging()
    # Não deve levantar, mesmo que o destino final não encode o caractere.
    logging.getLogger("apolo.teste").info("setinha → e sol ☀️ no log")
