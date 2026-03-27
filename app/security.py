from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64
PASSWORD_HASH_SCHEME = "scrypt"


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
    )
    return "$".join(
        [
            PASSWORD_HASH_SCHEME,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            _encode_bytes(salt),
            _encode_bytes(derived_key),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, n_value, r_value, p_value, salt_value, expected_value = password_hash.split("$", 5)
    except ValueError:
        return False

    if scheme != PASSWORD_HASH_SCHEME:
        return False

    derived_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=_decode_bytes(salt_value),
        n=int(n_value),
        r=int(r_value),
        p=int(p_value),
        dklen=SCRYPT_DKLEN,
    )
    return hmac.compare_digest(_encode_bytes(derived_key), expected_value)


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
