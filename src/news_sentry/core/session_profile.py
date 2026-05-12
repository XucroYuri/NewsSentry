"""Implements: SessionProfile 治理模块 (Phase 6 Sandbox Hardening)。

SessionProfile 元数据管理：browser profile 审批、敏感数据保护。
Storage: memory/session-profiles/ 目录（YAML 文件）。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationInfo, field_validator

SENSITIVE_KEYWORDS = [
    "cookie",
    "token",
    "password",
    "session_key",
    "access_token",
    "bearer",
    "secret",
]


class SessionProfile(BaseModel):
    """SessionProfile 元数据文件（存入 memory/session-profiles/）。

    严格约束：不存储 cookie/token/password 字面值。
    """

    profile_id: str
    display_name: str
    platform: str  # "twitter" | "weixin" | "zhihu" | ...
    auth_owner: str  # 必须是 "human-approved"
    approved_by: str
    approved_at: str  # ISO datetime string
    account_type: str  # "public-account" | "personal-account"
    risk_level: str  # "low" | "medium" | "high"
    profile_path: str  # Chrome profile 路径
    notes: str = ""

    @field_validator("auth_owner")
    @classmethod
    def auth_owner_must_be_human_approved(cls, v: str) -> str:
        if v != "human-approved":
            raise ValueError(f"auth_owner 必须是 'human-approved'，当前值: '{v}'")
        return v

    @field_validator("*")
    @classmethod
    def no_sensitive_data(cls, v: str, info: ValidationInfo) -> str:
        # Skip non-string fields
        if not isinstance(v, str):
            return v
        v_lower = v.lower()
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in v_lower:
                raise ValueError(f"字段 '{info.field_name}' 包含敏感关键词 '{keyword}'，禁止存储")
        return v


def load_session_profiles(
    profiles_dir: Path | str,
) -> dict[str, SessionProfile]:
    """从 profiles_dir 加载所有 SessionProfile YAML 文件。

    Args:
        profiles_dir: session-profiles 目录路径。

    Returns:
        以 profile_id 为键的 SessionProfile 字典。不存在的目录返回空字典。
    """
    dir_path = Path(profiles_dir)
    if not dir_path.exists() or not dir_path.is_dir():
        return {}

    profiles: dict[str, SessionProfile] = {}
    for yaml_file in dir_path.glob("*.yaml"):
        with open(yaml_file, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        profile = SessionProfile.model_validate(data)
        profiles[profile.profile_id] = profile

    return profiles


def validate_no_sensitive_data(profile: SessionProfile) -> None:
    """验证 SessionProfile 实例不包含敏感数据。

    检查所有字段值（转为字符串后）是否包含敏感关键词。
    同时检查可能通过 extra fields 添加的字段。

    Args:
        profile: SessionProfile 实例。

    Raises:
        ValueError: 如果发现敏感数据。
    """
    for field_name, field_value in profile.model_dump().items():
        if field_value is None:
            continue
        value_str = str(field_value).lower()
        for keyword in SENSITIVE_KEYWORDS:
            if keyword in value_str:
                raise ValueError(f"字段 '{field_name}' 包含敏感关键词 '{keyword}'，禁止存储")
