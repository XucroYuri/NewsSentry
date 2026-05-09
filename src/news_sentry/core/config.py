"""Implements: docs/spec/phase-3-kernel-mvp.md §3.3

ConfigLoader — loads and deep-merges config YAML files per ADR-0015.
Load order: target → source → sandbox (target has highest priority).

JSON Schema 校验 per ADR-0014, contracts-canonical.md §10.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate as jsonschema_validate
from pydantic import BaseModel, Field


class ResolvedConfig(BaseModel):
    """完整解析后的一个 target 的运行时配置。

    字段类型为 raw dict — JSON Schema 已在加载阶段校验，
    此处不重复做 pydantic 级别的细粒度验证。
    """

    target: dict[str, Any]
    """TargetConfig 数据（来自 config/targets/{id}.yaml）"""

    sources: list[dict[str, Any]] = Field(default_factory=list)
    """SourceChannel 列表（来自 config/sources/{target_id}/*.yaml）"""

    filter_rules: dict[str, Any] = Field(default_factory=dict)
    """FilterRules 数据（来自 filter_rules_ref）"""

    classification_rules: dict[str, Any] = Field(default_factory=dict)
    """ClassificationRules 数据（来自 classification_rules_ref）"""

    sandbox_policy: dict[str, Any] = Field(default_factory=dict)
    """SandboxPolicy 数据（来自 sandbox_profile_ref）"""

    provider_routes: dict[str, Any] = Field(default_factory=dict)
    """ProviderConfig 数据（来自 provider_routes_ref）"""

    output_destinations: dict[str, Any] = Field(default_factory=dict)
    """输出目的地配置（来自 output_destinations_ref）"""

    @property
    def target_id(self) -> str:
        """从 target 配置中提取 target_id。"""
        return str(self.target["target_id"])


class ConfigLoader:
    """加载和校验配置文件，per ADR-0014 (JSON Schema) 和 ADR-0015 (merge priority)。"""

    _SCHEMA_HEADER_RE = re.compile(r"^#\s*Schema:\s*(.+?)\s*$", re.MULTILINE)

    def __init__(self, config_root: Path) -> None:
        """初始化 ConfigLoader。

        Args:
            config_root: 项目根目录（包含 config/、schemas/ 子目录）。
        """
        self._config_root = config_root

    # ── 公共接口 ─────────────────────────────────────────────

    def load_target(self, target_id: str) -> ResolvedConfig:
        """加载 target 的完整配置：加载 YAML → 解析引用 → 合并 → 校验。

        Args:
            target_id: target 标识符（如 "italy"）。

        Returns:
            包含所有子配置的 ResolvedConfig。

        Raises:
            FileNotFoundError: target 配置文件不存在。
            ValidationError: JSON Schema 校验失败。
        """
        target_path = self._config_root / "config" / "targets" / f"{target_id}.yaml"
        if not target_path.is_file():
            raise FileNotFoundError(
                f"Target 配置文件不存在: {target_path}"
            )

        target_data = self._load_yaml(target_path)
        self._validate_resolved_schema(target_data, target_path)

        sources = self._load_sources(target_id, target_data.get("source_channel_refs", []))
        filter_rules = self._load_referenced_config(
            target_data.get("filter_rules_ref"), target_path
        )
        classification_rules = self._load_referenced_config(
            target_data.get("classification_rules_ref"), target_path
        )
        sandbox_policy = self._load_referenced_config(
            target_data.get("sandbox_profile_ref"), target_path
        )
        provider_routes = self._load_referenced_config(
            target_data.get("provider_routes_ref"), target_path
        )
        output_destinations = self._load_referenced_config(
            target_data.get("output_destinations_ref"), target_path
        )

        return ResolvedConfig(
            target=target_data,
            sources=sources,
            filter_rules=filter_rules,
            classification_rules=classification_rules,
            sandbox_policy=sandbox_policy,
            provider_routes=provider_routes,
            output_destinations=output_destinations,
        )

    # ── 内部方法 ─────────────────────────────────────────────

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """加载 YAML 文件并返回原始 dict。

        # Schema: 头部注释仅在上层方法中用于解析 schema 路径，
        本方法不负责校验。

        Args:
            path: YAML 文件的绝对路径。

        Returns:
            解析后的 dict（保证不为空；空文件返回 {}）。

        Raises:
            FileNotFoundError: 文件不存在。
            yaml.YAMLError: YAML 语法错误。
        """
        with open(path, encoding="utf-8") as fh:
            data: Any = yaml.safe_load(fh)
        if not isinstance(data, dict):
            return {}
        return data

    def _validate(self, data: dict[str, Any], schema_path: Path) -> None:
        """用 JSON Schema 校验数据。

        Args:
            data: 待校验的 dict。
            schema_path: JSON Schema 文件的绝对路径。

        Raises:
            FileNotFoundError: Schema 文件不存在。
            ValidationError: 校验失败。
        """
        if not schema_path.is_file():
            raise FileNotFoundError(f"Schema 文件不存在: {schema_path}")
        with open(schema_path, encoding="utf-8") as fh:
            schema = yaml.safe_load(fh)
        # jsonschema.validate 在失败时自动抛出 ValidationError
        jsonschema_validate(instance=data, schema=schema)

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """递归合并两个 dict。

        规则：
        - 两个 dict 均有的 key：递归合并 value。
        - override 独有的 key：直接加入结果。
        - list 类型：override 直接替换 base（不做 append）。
        - 非 dict 类型：override 覆盖 base。

        Args:
            base: 基础配置。
            override: 覆盖配置（优先级更高）。

        Returns:
            合并后的新 dict。
        """
        result: dict[str, Any] = dict(base)
        for key, val in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge(result[key], val)
            else:
                result[key] = val
        return result

    # ── 私有辅助方法 ─────────────────────────────────────────

    @classmethod
    def _extract_schema_ref(cls, raw_text: str) -> str | None:
        """从 YAML 文本头部提取 # Schema: 注释。

        Args:
            raw_text: YAML 文件原始文本。

        Returns:
            Schema 文件相对路径，无匹配时返回 None。
        """
        m = cls._SCHEMA_HEADER_RE.search(raw_text)
        if m is None:
            return None
        return m.group(1).strip()

    def _resolve_schema_path(self, yaml_path: Path) -> Path | None:
        """从 YAML 头部 # Schema: 注释解析 schema 文件路径。

        解析策略：
        1. 将 # Schema: 路径相对于 YAML 文件目录解析。
        2. 若步骤 1 不存在：提取 schema 文件名，在 config_root/schemas/ 下查找。

        Args:
            yaml_path: YAML 源文件路径。

        Returns:
            解析后的 schema 绝对路径，无声明或找不到时返回 None。
        """
        raw_text = yaml_path.read_text(encoding="utf-8")
        schema_ref = self._extract_schema_ref(raw_text)
        if schema_ref is None:
            return None
        # 优先相对于 YAML 文件所在目录
        candidate = (yaml_path.parent / schema_ref).resolve()
        if candidate.is_file():
            return candidate
        # 回退：直接在 config_root/schemas/ 目录按文件名查找
        schema_name = Path(schema_ref).name
        candidate = (self._config_root / "schemas" / schema_name).resolve()
        if candidate.is_file():
            return candidate
        return None

    def _validate_resolved_schema(self, data: dict[str, Any], yaml_path: Path) -> None:
        """读取 YAML 头部的 # Schema: 注释并校验 data。

        Args:
            data: 已解析的 YAML 数据。
            yaml_path: YAML 源文件路径（用于解析相对 schema 路径）。
        """
        schema_path = self._resolve_schema_path(yaml_path)
        if schema_path is None:
            return  # 无 schema 声明或找不到 schema 文件，跳过校验
        self._validate(data, schema_path)

    def _load_referenced_config(self, ref_path_str: str | None,
                                context_path: Path) -> dict[str, Any]:
        """加载 target YAML 中引用的子配置文件。

        ref_path_str 可以是相对于 config_root 的路径，也可以是相对路径。
        解析顺序：
        1. 尝试当作相对于 config_root 的路径
        2. 尝试当作相对于 context_path 父目录的路径

        Args:
            ref_path_str: 引用路径字符串（如 "config/filters/italy/default.yaml"）。
            context_path: 包含此引用的 YAML 文件路径。

        Returns:
            已校验的配置 dict。ref 不存在时返回空 dict。
        """
        if ref_path_str is None:
            return {}
        ref_path = self._config_root / ref_path_str
        if not ref_path.is_file():
            ref_path = (context_path.parent / ref_path_str).resolve()
        if not ref_path.is_file():
            return {}
        data = self._load_yaml(ref_path)
        self._validate_resolved_schema(data, ref_path)
        return data

    def _load_sources(self, target_id: str,
                      source_ids: list[str]) -> list[dict[str, Any]]:
        """加载 target 的所有 source channel 配置。

        Args:
            target_id: target 标识符（如 "italy"）。
            source_ids: source channel ID 列表（如 ["ansa", "repubblica"]）。

        Returns:
            SourceChannel 数据列表（已校验）。
        """
        sources: list[dict[str, Any]] = []
        sources_dir = self._config_root / "config" / "sources" / target_id
        for sid in source_ids:
            source_path = sources_dir / f"{sid}.yaml"
            if not source_path.is_file():
                raise FileNotFoundError(
                    f"Source 配置文件不存在: {source_path}"
                )
            data = self._load_yaml(source_path)
            self._validate_resolved_schema(data, source_path)
            sources.append(data)
        return sources
