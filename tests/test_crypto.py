"""Criptografia em repouso (M11, Épico 11.2).

Trava as garantias: round-trip fiel, senha ERRADA falha, arquivo ADULTERADO
falha (autenticado), salt novo a cada cifragem (mesmo texto → saídas diferentes),
e envelope autodescritivo (MAGIC + salt embutido).
"""
import pytest

from src import crypto

pytestmark = pytest.mark.skipif(not crypto.is_available(),
                                reason="cryptography não instalado")

PW = "uma senha bem forte 123"


def test_round_trip_bytes():
    blob = crypto.encrypt_bytes(b"segredo do Leo", PW)
    assert blob[:8] == crypto.MAGIC
    assert crypto.decrypt_bytes(blob, PW) == b"segredo do Leo"


def test_round_trip_json():
    obj = {"topicos": ["a", "b"], "n": 42, "acentuação": "ção"}
    assert crypto.decrypt_json(crypto.encrypt_json(obj, PW), PW) == obj


def test_senha_errada_falha():
    blob = crypto.encrypt_bytes(b"x", PW)
    with pytest.raises(Exception):
        crypto.decrypt_bytes(blob, "senha errada")


def test_adulteracao_e_detectada():
    blob = bytearray(crypto.encrypt_bytes(b"conteudo importante", PW))
    blob[-1] ^= 0x01                      # vira 1 bit do token
    with pytest.raises(Exception):
        crypto.decrypt_bytes(bytes(blob), PW)


def test_cabecalho_invalido_rejeitado():
    with pytest.raises(ValueError):
        crypto.decrypt_bytes(b"NAOEHBACKUP" + b"x" * 40, PW)


def test_salt_novo_a_cada_cifragem():
    a = crypto.encrypt_bytes(b"mesmo texto", PW)
    b = crypto.encrypt_bytes(b"mesmo texto", PW)
    assert a != b                         # salt aleatório → cifrados diferentes
    assert crypto.decrypt_bytes(a, PW) == crypto.decrypt_bytes(b, PW)


def test_senha_vazia_recusada():
    with pytest.raises(ValueError):
        crypto.encrypt_bytes(b"x", "")
