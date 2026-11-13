"""密码与令牌哈希（契约 `C-HASH@1`，owner = T2）。

密码使用标准库 ``hashlib.scrypt``（n=2^14, r=8, p=1，16 字节 salt）——环境无法安装
``argon2-cffi``，对「优先 Argon2id」的替代偏差已记录在 design.md 开放决策 1。
令牌（session / 邀请 / 重置）只存 SHA-256 十六进制，禁止任何可逆编码。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1

_SALT_BYTES = 16
_DERIVED_BYTES = 32
_SCHEME = "scrypt"
# OpenSSL 默认上限 32MB，显式放宽避免参数组合逼近边界时抛 ValueError
_MAXMEM = 64 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=_DERIVED_BYTES,
        maxmem=_MAXMEM,
    )


def hash_password(password: str) -> str:
    """返回 ``scrypt$16384$8$1$<salt_b64>$<hash_b64>`` 格式的密码哈希。"""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join([_SCHEME, str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P), _b64(salt), _b64(digest)])


def verify_password(password: str, stored: str | None) -> bool:
    """校验密码；任何格式异常一律返回 ``False``，不抛异常。"""
    if not password or not stored or not stored.startswith(f"{_SCHEME}$"):
        return False
    parts = stored.split("$")
    if len(parts) != 6:
        return False
    _, n_text, r_text, p_text, salt_text, digest_text = parts
    if (n_text, r_text, p_text) != (str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P)):
        return False
    try:
        salt = base64.b64decode(salt_text, validate=True)
        expected = base64.b64decode(digest_text, validate=True)
        actual = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    """令牌的单向摘要（sha256 十六进制）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token(nbytes: int = 32) -> str:
    """生成 URL 安全的高熵明文令牌（只返回给调用方一次，库中只存 ``hash_token``）。"""
    return secrets.token_urlsafe(nbytes)


__all__ = [
    "SCRYPT_N",
    "SCRYPT_R",
    "SCRYPT_P",
    "hash_password",
    "verify_password",
    "hash_token",
    "new_token",
]