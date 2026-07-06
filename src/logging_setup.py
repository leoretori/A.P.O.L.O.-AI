"""Logging estruturado (Épico 1.3 / observabilidade do JARVIS_ROADMAP).

Dois formatos, escolhidos por env `LOG_FORMAT`:
- `text` (padrão): legível no terminal, como sempre foi.
- `json`: uma linha JSON por evento — parseável por ferramentas de log
  (grep/jq, futuros coletores). Cada linha traz ts ISO, nível, logger, mensagem
  e quaisquer campos `extra` passados no log (ex.: `logger.info(msg, extra={...})`).

Uso: `configure_logging()` no boot, substituindo o `logging.basicConfig` antigo.
"""

import json
import logging
import os
import sys

# Bibliotecas que geram 1 log por requisição de rede — silenciadas em produção.
NOISY = ("httpx", "httpcore", "watchfiles", "chromadb.telemetry")

# Atributos padrão de um LogRecord — tudo FORA disso é campo "extra" do usuário.
_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Formata cada log como uma linha JSON, preservando campos `extra`."""

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Campos extras passados via logger.x(..., extra={...}).
        for k, v in record.__dict__.items():
            if k not in _RESERVED and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging(level_name: str | None = None, fmt: str | None = None) -> str:
    """Configura o logging raiz. Retorna o formato ativo ('json'|'text').

    - `level_name`: nível (INFO/DEBUG/...); default via env `LOG_LEVEL` ou INFO.
    - `fmt`: 'json' ou 'text'; default via env `LOG_FORMAT` ou 'text'.
    Idempotente: substitui os handlers do root a cada chamada.
    """
    level_name = (level_name or os.getenv("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = (fmt or os.getenv("LOG_FORMAT", "text")).lower()

    handler = logging.StreamHandler(sys.stderr)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    for noisy in NOISY:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return "json" if fmt == "json" else "text"
