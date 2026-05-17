"""认证工具 — 密码 hash/verify，零外部依赖。"""

from __future__ import annotations

import hashlib
import os
import secrets

__all__ = ["hash_password", "verify_password"]

# OWASP 推荐: PBKDF2-SHA256, 600k iterations
_PBKDF2_ITERATIONS = 600_000
_SALT_SIZE = 32


def hash_password(password: str) -> tuple[str, str]:
    """对密码进行 hash，返回 (password_hash_hex, salt_hex)。"""
    salt = os.urandom(_SALT_SIZE)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return dk.hex(), salt.hex()


def verify_password(password: str, password_hash_hex: str, salt_hex: str) -> bool:
    """常量时间密码验证。"""
    salt = bytes.fromhex(salt_hex)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return secrets.compare_digest(dk.hex(), password_hash_hex)
