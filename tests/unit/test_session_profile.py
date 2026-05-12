"""session_profile 模块测试 — SessionProfile + load_session_profiles + validate_no_sensitive_data"""
# ruff: noqa: S108  # /tmp/ 路径仅作测试 mock 参数，不执行实际文件操作

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from news_sentry.core.session_profile import (
    SessionProfile,
    load_session_profiles,
    validate_no_sensitive_data,
)

# ── helpers ────────────────────────────────────────────────────


def _make_valid_profile(**overrides) -> dict:
    data = {
        "profile_id": "test-profile-1",
        "display_name": "测试账号",
        "platform": "twitter",
        "auth_owner": "human-approved",
        "approved_by": "admin",
        "approved_at": "2026-05-11T10:00:00+00:00",
        "account_type": "public-account",
        "risk_level": "low",
        "profile_path": "/home/user/chrome-profiles/test",
        "notes": "测试用 session profile",
    }
    data.update(overrides)
    return data


# ── SessionProfile ─────────────────────────────────────────────


class TestSessionProfileValid:
    def test_valid_construction(self):
        """正常构造 SessionProfile 应成功。"""
        profile = SessionProfile(**_make_valid_profile())
        assert profile.profile_id == "test-profile-1"
        assert profile.display_name == "测试账号"
        assert profile.auth_owner == "human-approved"
        assert profile.risk_level == "low"
        assert profile.notes == "测试用 session profile"

    def test_default_notes(self):
        """notes 默认值为空字符串。"""
        data = _make_valid_profile()
        del data["notes"]
        profile = SessionProfile(**data)
        assert profile.notes == ""

    def test_valid_profile_with_extra_fields_ignored(self):
        """额外字段应被忽略（Pydantic 默认行为）。"""
        data = _make_valid_profile(extra_field="should_be_ignored")
        profile = SessionProfile(**data)
        assert not hasattr(profile, "extra_field")


class TestSessionProfileAuthOwner:
    def test_auth_owner_not_human_approved_raises(self):
        """auth_owner 不是 'human-approved' 时应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="auth_owner"):
            SessionProfile(**_make_valid_profile(auth_owner="auto-approved"))

    def test_auth_owner_empty_string_raises(self):
        """auth_owner 为空字符串也应被拒绝。"""
        with pytest.raises(ValidationError, match="auth_owner"):
            SessionProfile(**_make_valid_profile(auth_owner=""))

    def test_auth_owner_near_match_raises(self):
        """接近但不完全匹配的值（如 'Human-Approved'）应被拒绝。"""
        with pytest.raises(ValidationError, match="auth_owner"):
            SessionProfile(**_make_valid_profile(auth_owner="Human-Approved"))


class TestSessionProfileSensitiveData:
    def test_field_containing_cookie_raises(self):
        """字段值包含 'cookie'（任意大小写）应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(notes="auth_cookie=abc123"))

    def test_field_containing_cookie_uppercase_raises(self):
        """字段值包含 'COOKIE' 大写形式应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(display_name="my_COOKIE_account"))

    def test_field_containing_bearer_raises(self):
        """字段值包含 'bearer' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(profile_path="/tmp/bearer_token"))

    def test_field_containing_token_raises(self):
        """字段值包含 'token' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(notes="access_token: xyz"))

    def test_field_containing_password_raises(self):
        """字段值包含 'password' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(notes="password=secret"))

    def test_field_containing_session_key_raises(self):
        """字段值包含 'session_key' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(profile_path="/tmp/session_key_store"))

    def test_field_containing_access_token_raises(self):
        """字段值包含 'access_token' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(notes="my access_token here"))

    def test_field_containing_secret_raises(self):
        """字段值包含 'secret' 应抛出 ValidationError。"""
        with pytest.raises(ValidationError, match="敏感关键词"):
            SessionProfile(**_make_valid_profile(notes="client_secret=42"))

    def test_clean_fields_pass(self):
        """不含任何敏感关键词的字段应通过验证。"""
        profile = SessionProfile(
            **_make_valid_profile(
                notes="公开账号，无敏感信息",
                display_name="NewsBot Official",
                profile_path="/home/user/chrome-profiles/newsbot",
            )
        )
        assert profile.notes == "公开账号，无敏感信息"


# ── load_session_profiles ──────────────────────────────────────


class TestLoadSessionProfiles:
    def test_loads_valid_yaml_files(self, tmp_path: Path):
        """从目录加载多个有效 YAML 文件。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        p1 = _make_valid_profile(profile_id="p1", display_name="账号1")
        p2 = _make_valid_profile(profile_id="p2", display_name="账号2")

        (profiles_dir / "p1.yaml").write_text(yaml.dump(p1, allow_unicode=True), encoding="utf-8")
        (profiles_dir / "p2.yaml").write_text(yaml.dump(p2, allow_unicode=True), encoding="utf-8")

        profiles = load_session_profiles(profiles_dir)

        assert len(profiles) == 2
        assert "p1" in profiles
        assert "p2" in profiles
        assert profiles["p1"].display_name == "账号1"
        assert profiles["p2"].display_name == "账号2"

    def test_loads_single_yaml_file(self, tmp_path: Path):
        """加载单个 YAML 文件。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        data = _make_valid_profile()
        (profiles_dir / "test.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )

        profiles = load_session_profiles(profiles_dir)
        assert len(profiles) == 1
        assert profiles["test-profile-1"].platform == "twitter"

    def test_non_existent_dir_returns_empty(self, tmp_path: Path):
        """不存在目录时返回空字典。"""
        profiles = load_session_profiles(tmp_path / "does-not-exist")
        assert profiles == {}

    def test_dir_path_as_string(self, tmp_path: Path):
        """传入字符串路径也应正常工作。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        data = _make_valid_profile()
        (profiles_dir / "test.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )

        profiles = load_session_profiles(str(profiles_dir))
        assert len(profiles) == 1

    def test_empty_yaml_files_skipped(self, tmp_path: Path):
        """空 YAML 文件（解析为 None）应被跳过。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        valid = _make_valid_profile(profile_id="valid")
        (profiles_dir / "valid.yaml").write_text(
            yaml.dump(valid, allow_unicode=True), encoding="utf-8"
        )
        (profiles_dir / "empty.yaml").write_text("", encoding="utf-8")

        profiles = load_session_profiles(profiles_dir)
        assert len(profiles) == 1
        assert "valid" in profiles

    def test_invalid_yaml_raises(self, tmp_path: Path):
        """包含敏感关键词的 YAML 在加载时抛出 ValidationError。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        bad_data = _make_valid_profile(profile_id="bad", notes="cookie=secret")
        (profiles_dir / "bad.yaml").write_text(
            yaml.dump(bad_data, allow_unicode=True), encoding="utf-8"
        )

        with pytest.raises(ValidationError):
            load_session_profiles(profiles_dir)

    def test_only_yaml_files_loaded(self, tmp_path: Path):
        """只加载 .yaml 文件，忽略其他后缀。"""
        profiles_dir = tmp_path / "profiles"
        profiles_dir.mkdir()

        data = _make_valid_profile()
        (profiles_dir / "test.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )
        (profiles_dir / "readme.txt").write_text("not a profile", encoding="utf-8")

        profiles = load_session_profiles(profiles_dir)
        assert len(profiles) == 1


# ── validate_no_sensitive_data ─────────────────────────────────


class TestValidateNoSensitiveData:
    def test_clean_profile_passes(self):
        """不含敏感数据的 profile 应通过验证。"""
        profile = SessionProfile(**_make_valid_profile())
        validate_no_sensitive_data(profile)  # 不应抛出异常

    def test_profile_with_token_raises_valueerror(self):
        """包含 'token' 的字段应抛出 ValueError。

        使用 model_construct 绕过 Pydantic 构造时验证，直接测试双检函数。
        """
        data = _make_valid_profile(notes="my_token_here")
        profile = SessionProfile.model_construct(**data)
        with pytest.raises(ValueError, match="token"):
            validate_no_sensitive_data(profile)

    def test_profile_with_none_fields_skipped(self):
        """None 字段应被 validate_no_sensitive_data 跳过。"""
        data = _make_valid_profile()
        data["notes"] = None
        profile = SessionProfile.model_construct(**data)
        validate_no_sensitive_data(profile)  # 不应抛出

    def test_profile_with_cookie_raises_valueerror(self):
        """包含 'cookie' 的字段应抛出 ValueError。"""
        data = _make_valid_profile(notes="set-cookie: abc")
        profile = SessionProfile.model_construct(**data)
        with pytest.raises(ValueError, match="cookie"):
            validate_no_sensitive_data(profile)

    def test_profile_with_bearer_raises_valueerror(self):
        """包含 'bearer' 的字段应抛出 ValueError。"""
        data = _make_valid_profile(notes="bearer abc123")
        profile = SessionProfile.model_construct(**data)
        with pytest.raises(ValueError, match="bearer"):
            validate_no_sensitive_data(profile)

    def test_profile_with_secret_raises_valueerror(self):
        """包含 'secret' 的字段应抛出 ValueError。"""
        data = _make_valid_profile(notes="my_secret_key")
        profile = SessionProfile.model_construct(**data)
        with pytest.raises(ValueError, match="secret"):
            validate_no_sensitive_data(profile)

    def test_clean_profile_with_all_fields(self):
        """验证包含所有正常字段的 profile 通过双重验证。"""
        data = _make_valid_profile()
        profile = SessionProfile(**data)
        # 第一层：构造时通过
        validate_no_sensitive_data(profile)  # 第二层：显式调用也通过
        assert profile.profile_id == "test-profile-1"
