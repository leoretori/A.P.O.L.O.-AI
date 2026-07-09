"""Criptografia em repouso (M11, Épico 11.2).

Cifra dados sensíveis (backups) com uma SENHA que só você conhece — nada sai em
texto puro no disco. Padrão à prova de erro: derivação de chave por **scrypt**
(lento de propósito, resiste a força bruta) + **Fernet** (AES-128-CBC + HMAC-SHA256,
AUTENTICADO — detecta adulteração). A senha nunca é gravada; a chave é derivada na
hora a partir da senha + um `salt` aleatório embutido no próprio arquivo.

Envelope autodescritivo: MAGIC(8) + salt(16) + token Fernet. Assim o arquivo
carrega o salt e a versão — para decifrar basta a senha. Núcleo determinístico e
testável (round-trip; senha errada e adulteração FALHAM de forma limpa).
"""
from __future__ import annotations

import base64
import hashlib
import os

MAGIC = b"APOLOBK1"          # 8 bytes — versão do envelope
SALT_LEN = 16
_SCRYPT_N = 2 ** 14          # custo de CPU/memória (~16 MB) — lento p/ atacante
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def is_available() -> bool:
    """A lib de cifra autenticada está instalada? (degradação honesta, como o Piper.)"""
    try:
        import cryptography.fernet  # noqa: F401
        return True
    except Exception:
        return False


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """Senha + salt → chave de 32 bytes (scrypt) no formato base64 do Fernet."""
    if not passphrase:
        raise ValueError("senha vazia")
    raw = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt,
                         n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P,
                         maxmem=_SCRYPT_MAXMEM, dklen=32)
    return base64.urlsafe_b64encode(raw)


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Cifra `data` com a senha. Cada chamada usa um salt novo → mesmo texto gera
    saídas diferentes (não vaza igualdade)."""
    from cryptography.fernet import Fernet
    salt = os.urandom(SALT_LEN)
    token = Fernet(derive_key(passphrase, salt)).encrypt(data)
    return MAGIC + salt + token


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decifra um envelope de `encrypt_bytes`. Levanta ValueError se o formato não
    bate; a senha errada / arquivo adulterado levanta cryptography InvalidToken."""
    if not blob or blob[:len(MAGIC)] != MAGIC:
        raise ValueError("não é um backup do A.P.O.L.O. (cabeçalho inválido)")
    off = len(MAGIC)
    salt = blob[off:off + SALT_LEN]
    token = blob[off + SALT_LEN:]
    from cryptography.fernet import Fernet
    return Fernet(derive_key(passphrase, salt)).decrypt(token)


def encrypt_json(obj, passphrase: str) -> bytes:
    import json
    return encrypt_bytes(json.dumps(obj, ensure_ascii=False).encode("utf-8"), passphrase)


def decrypt_json(blob: bytes, passphrase: str):
    import json
    return json.loads(decrypt_bytes(blob, passphrase).decode("utf-8"))
