"""Backup local cifrado + restauração testada (M11, Épico 11.2)."""
import tempfile
from pathlib import Path

import pytest

from src import backup_service as B
from src import crypto

pytestmark = pytest.mark.skipif(not crypto.is_available(),
                                reason="cryptography não instalado")

PW = "senha-do-backup"


def test_write_e_read_round_trip():
    d = Path(tempfile.mkdtemp())
    data = {"counts": {"learned_topics": 3}, "learned_topics": [{"topic": "x"}]}
    info = B.write_encrypted(data, PW, out_dir=d)
    assert info["name"].endswith(B.EXT) and info["bytes"] > 0
    # o arquivo NÃO contém o texto em claro
    raw = Path(info["path"]).read_bytes()
    assert b"learned_topics" not in raw and raw[:8] == crypto.MAGIC
    assert B.read_encrypted(info["path"], PW) == data


def test_read_senha_errada_falha():
    d = Path(tempfile.mkdtemp())
    info = B.write_encrypted({"a": 1}, PW, out_dir=d)
    with pytest.raises(Exception):
        B.read_encrypted(info["path"], "outra senha")


def test_list_backups_ordena_recentes():
    d = Path(tempfile.mkdtemp())
    B.write_encrypted({"a": 1}, PW, out_dir=d)
    B.write_encrypted({"a": 2}, PW, out_dir=d)
    items = B.list_backups(d)
    assert len(items) == 2 and all(i["name"].endswith(B.EXT) for i in items)


def test_prune_mantem_os_mais_recentes():
    d = Path(tempfile.mkdtemp())
    for i in range(5):
        B.write_encrypted({"a": i}, PW, out_dir=d)
    removed = B.prune_backups(keep=2, out_dir=d)
    assert removed == 3 and len(B.list_backups(d)) == 2


def test_write_sem_senha_recusa():
    with pytest.raises(ValueError):
        B.write_encrypted({"a": 1}, "", out_dir=Path(tempfile.mkdtemp()))
