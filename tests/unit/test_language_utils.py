"""Tests for skills/collect/language_utils.py."""

from __future__ import annotations

from news_sentry.models.newsevent import Language
from news_sentry.skills.collect.language_utils import coerce_language


class TestCoerceLanguage:
    def test_passthrough_language_enum(self) -> None:
        """已为 Language 枚举时直接返回。"""
        assert coerce_language(Language.IT) == Language.IT

    def test_none_returns_default(self) -> None:
        """None 返回默认值。"""
        assert coerce_language(None) == Language.MIXED
        assert coerce_language(None, default=Language.EN) == Language.EN

    def test_empty_string_returns_default(self) -> None:
        """空字符串返回默认值。"""
        assert coerce_language("") == Language.MIXED
        assert coerce_language("  ") == Language.MIXED

    def test_valid_code(self) -> None:
        """有效的语言代码被正确转换。"""
        assert coerce_language("it") == Language.IT
        assert coerce_language("en") == Language.EN
        assert coerce_language("zh") == Language.ZH
        assert coerce_language("ja") == Language.JA

    def test_code_with_variant(self) -> None:
        """zh-CN, en-US 等变体取主代码。"""
        assert coerce_language("zh-CN") == Language.ZH
        assert coerce_language("en_US") == Language.EN

    def test_invalid_code_returns_default(self) -> None:
        """无效代码返回默认值。"""
        assert coerce_language("xyz") == Language.MIXED
        assert coerce_language("not_a_lang") == Language.MIXED
