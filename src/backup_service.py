"""Backup local criptografado + restauração (M11, Épico 11.2).

Grava um snapshot cifrado (o export completo do banco) num arquivo `.apolobak`
local — nada em texto puro. A restauração lê o arquivo, decifra com a senha e
devolve os dados (o caller importa via `db.import_all`). O agendador pode fazer um
backup diário automático se `BACKUP_PASSPHRASE` estiver no `.env`.

Separação testável: este módulo cuida de ARQUIVO + CIFRA; a serialização/importação
do banco fica no caller (reusa export_all/import_all que já existem).
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime
from pathlib import Path

from src import crypto

logger = logging.getLogger("apolo.backup")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "data/backups"))
EXT = ".apolobak"


def backup_filename(now: datetime | None = None) -> str:
    # Sufixo aleatório curto → nomes únicos mesmo com vários backups no mesmo segundo.
    now = now or datetime.now()
    return f"apolo-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}{EXT}"


def write_encrypted(data: dict, passphrase: str, out_dir: Path | str | None = None) -> dict:
    """Cifra `data` com a senha e grava em out_dir. Retorna {path, name, bytes}."""
    if not passphrase:
        raise ValueError("informe uma senha para cifrar o backup")
    out = Path(out_dir) if out_dir else BACKUP_DIR
    out.mkdir(parents=True, exist_ok=True)
    blob = crypto.encrypt_json(data, passphrase)
    path = out / backup_filename()
    path.write_bytes(blob)
    return {"path": str(path), "name": path.name, "bytes": len(blob)}


def read_encrypted(path: str | Path, passphrase: str) -> dict:
    """Lê e decifra um `.apolobak`. Senha errada/arquivo adulterado → exceção."""
    blob = Path(path).read_bytes()
    data = crypto.decrypt_json(blob, passphrase)
    if not isinstance(data, dict):
        raise ValueError("conteúdo do backup inesperado")
    return data


def list_backups(out_dir: Path | str | None = None) -> list[dict]:
    """Backups locais, mais recentes primeiro."""
    out = Path(out_dir) if out_dir else BACKUP_DIR
    if not out.is_dir():
        return []
    items = []
    for p in out.glob(f"*{EXT}"):
        try:
            st = p.stat()
        except OSError:
            continue
        items.append({"name": p.name, "path": str(p), "bytes": st.st_size,
                      "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return sorted(items, key=lambda x: x["modified"], reverse=True)


def prune_backups(keep: int = 14, out_dir: Path | str | None = None) -> int:
    """Mantém só os `keep` backups mais recentes (o auto-backup diário não enche o
    disco). Retorna quantos removeu."""
    items = list_backups(out_dir)
    removed = 0
    for it in items[keep:]:
        try:
            Path(it["path"]).unlink()
            removed += 1
        except OSError:
            pass
    return removed
