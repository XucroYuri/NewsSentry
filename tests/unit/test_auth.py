"""Tests for auth module — password hashing and verification."""

from __future__ import annotations

from news_sentry.core.auth import hash_password, verify_password


def test_hash_and_verify_password() -> None:
    """密码 hash + 验证正确性。"""
    pw_hash, salt = hash_password("my-secret-password")
    # hash 和 salt 都是 hex 字符串
    assert isinstance(pw_hash, str)
    assert isinstance(salt, str)
    assert len(pw_hash) == 64  # SHA-256 = 32 bytes = 64 hex chars
    assert len(salt) == 64  # 32 bytes = 64 hex chars
    # 正确密码验证通过
    assert verify_password("my-secret-password", pw_hash, salt)


def test_wrong_password_fails() -> None:
    """错误密码验证失败。"""
    pw_hash, salt = hash_password("correct-password")
    assert not verify_password("wrong-password", pw_hash, salt)


def test_empty_password() -> None:
    """空密码可 hash 但功能受限。"""
    pw_hash, salt = hash_password("")
    assert verify_password("", pw_hash, salt)
    assert not verify_password("not-empty", pw_hash, salt)


def test_different_salts_each_call() -> None:
    """每次调用生成不同 salt。"""
    pw_hash1, salt1 = hash_password("same-password")
    pw_hash2, salt2 = hash_password("same-password")
    # salt 应不同
    assert salt1 != salt2
    # hash 也应不同
    assert pw_hash1 != pw_hash2
    # 但都能验证原密码
    assert verify_password("same-password", pw_hash1, salt1)
    assert verify_password("same-password", pw_hash2, salt2)


def test_unicode_password() -> None:
    """Unicode 密码支持。"""
    pw_hash, salt = hash_password("密码测试🔐")
    assert verify_password("密码测试🔐", pw_hash, salt)
    assert not verify_password("密码测试🔓", pw_hash, salt)
