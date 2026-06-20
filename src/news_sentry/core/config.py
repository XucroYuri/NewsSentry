"""Implements: docs/spec/phase-3-kernel-mvp.md §3.3

ConfigLoader — loads and validates config YAML files per ADR-0015.
Load order: deployment profile → target → sources → sandbox policy.

JSON Schema 校验 per ADR-0014, contracts-canonical.md §10.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import validate as jsonschema_validate
from pydantic import BaseModel, Field

from news_sentry.skills.filter.classification_taxonomy import canonical_l0


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

    output_destinations: dict[str, Any] = Field(
        default_factory=lambda: {"markdown_auto_drafts": False}
    )
    """输出目的地配置（来自 output_destinations_ref）"""

    deployment_profile: dict[str, Any] = Field(default_factory=dict)
    """DeploymentProfile 数据（来自 config/profiles/{profile_id}.yaml）"""

    profile_id: str = "local-workstation"
    """当前 bounded run 使用的 deployment profile ID。"""

    output_root: Path = Path("data")
    """当前 bounded run 的已解析输出根目录。"""

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

    def load_profile(self, profile_id: str) -> dict[str, Any]:
        """加载 deployment profile。

        Args:
            profile_id: Profile 标识符，如 ``local-workstation`` 或 ``cloud-vps``。

        Returns:
            已校验的 DeploymentProfile dict。

        Raises:
            FileNotFoundError: profile 配置文件不存在。
            ValidationError: JSON Schema 校验失败。
        """
        profile_path = self._config_root / "config" / "profiles" / f"{profile_id}.yaml"
        if not profile_path.is_file():
            raise FileNotFoundError(f"Deployment profile 不存在: {profile_path}")
        data = self._load_yaml(profile_path)
        self._validate_resolved_schema(data, profile_path)
        return data

    def load_target(
        self,
        target_id: str,
        profile_id: str = "local-workstation",
        output_root_override: str | Path | None = None,
        allow_external_output_root: bool = False,
    ) -> ResolvedConfig:
        """加载 target 的完整配置：加载 YAML → 解析引用 → 合并 → 校验。

        Args:
            target_id: target 标识符（如 "italy"）。
            profile_id: Deployment profile 标识符。
            output_root_override: 可选数据根目录覆盖。
            allow_external_output_root: 是否允许输出根目录位于项目外。

        Returns:
            包含所有子配置的 ResolvedConfig。

        Raises:
            FileNotFoundError: target 配置文件不存在。
            ValidationError: JSON Schema 校验失败。
        """
        deployment_profile = self.load_profile(profile_id)

        target_path = self._config_root / "config" / "targets" / f"{target_id}.yaml"
        if not target_path.is_file():
            raise FileNotFoundError(f"Target 配置文件不存在: {target_path}")

        target_data = self._load_yaml(target_path)
        self._validate_resolved_schema(target_data, target_path)

        sources = self._load_sources(
            target_id,
            target_data.get("source_channel_refs", []),
            target_data,
        )
        filter_rules = self._load_referenced_config(
            target_data.get("filter_rules_ref"), target_path
        )
        classification_rules = self._load_classification_rules(
            target_data.get("classification_rules_ref"), target_path
        )
        # Phase 24: 将 target 配置中的 home_relevance_keywords 合并到 classification_rules
        target_classification = target_data.get("classification", {})
        hrk = "home_relevance_keywords"
        if isinstance(target_classification, dict) and hrk in target_classification:
            classification_rules[hrk] = target_classification[hrk]
        sandbox_ref = self._resolve_sandbox_ref(target_data, deployment_profile)
        sandbox_policy = self._load_referenced_config(sandbox_ref, target_path)
        if sandbox_ref is not None and not sandbox_policy:
            raise FileNotFoundError(f"Sandbox policy 配置文件不存在: {sandbox_ref}")
        provider_routes = self._load_referenced_config(
            target_data.get("provider_routes_ref"), target_path
        )
        output_destinations = self._load_referenced_config(
            target_data.get("output_destinations_ref"), target_path
        )
        output_destinations = self._with_output_defaults(output_destinations)
        output_root = self._resolve_output_root(
            deployment_profile,
            output_root_override,
            allow_external_output_root,
        )

        return ResolvedConfig(
            target=target_data,
            sources=sources,
            filter_rules=filter_rules,
            classification_rules=classification_rules,
            sandbox_policy=sandbox_policy,
            provider_routes=provider_routes,
            output_destinations=output_destinations,
            deployment_profile=deployment_profile,
            profile_id=profile_id,
            output_root=output_root,
        )

    def _with_output_defaults(self, output_destinations: dict[str, Any]) -> dict[str, Any]:
        """补齐输出策略默认值。"""
        return {"markdown_auto_drafts": False, **output_destinations}

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

    def _load_referenced_config(
        self, ref_path_str: str | None, context_path: Path
    ) -> dict[str, Any]:
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

    def _load_classification_rules(
        self,
        ref_path_str: str | None,
        context_path: Path,
    ) -> dict[str, Any]:
        """加载分类规则配置，支持 extends 继承机制。

        流程：
        1. 加载 ref 指向的 YAML 文件（不校验，因 extends 文件可能不含全量字段）
        2. 若存在 ``extends`` 键，加载基文件并递归解析其 extends
        3. 合并：dict 深层合并，list 为追加（基在前，子在后）
        4. 校验最终合并结果

        Args:
            ref_path_str: 引用路径字符串。
            context_path: 包含此引用的 YAML 文件路径。

        Returns:
            合并后的分类规则 dict。ref 不存在时返回空 dict。
        """
        if ref_path_str is None:
            return {}
        ref_path = self._resolve_ref_path(ref_path_str, context_path)
        if ref_path is None:
            return {}
        data = self._load_yaml(ref_path)
        merged = self._resolve_extends(data, ref_path_str, context_path)
        self._normalize_classification_rules(merged)
        # 对最终合并结果校验 schema
        self._validate_resolved_schema(merged, ref_path)
        return merged

    def _normalize_classification_rules(self, data: dict[str, Any]) -> None:
        for domain in data.get("l0_domains", []):
            if isinstance(domain, dict) and domain.get("code"):
                domain["code"] = canonical_l0(domain.get("code"))
        for topic in data.get("l1_topics", []):
            if isinstance(topic, dict) and topic.get("l0_domain"):
                topic["l0_domain"] = canonical_l0(topic.get("l0_domain"))

    def _resolve_ref_path(self, ref_path_str: str, context_path: Path) -> Path | None:
        """解析引用路径，与 _load_referenced_config 相同的查找逻辑。

        Args:
            ref_path_str: 引用路径字符串。
            context_path: 包含此引用的 YAML 文件路径。

        Returns:
            解析后的文件路径，找不到时返回 None。
        """
        ref_path = self._config_root / ref_path_str
        if not ref_path.is_file():
            ref_path = (context_path.parent / ref_path_str).resolve()
        if not ref_path.is_file():
            return None
        return ref_path

    def _resolve_extends(
        self,
        data: dict[str, Any],
        ref_path_str: str,
        context_path: Path,
    ) -> dict[str, Any]:
        """解析分类规则配置的 extends 继承链。

        递归加载基文件，并将当前 data 作为 overlay 合并上去。
        dict 键深层合并，list 键为追加（基在前，子在后）。

        Args:
            data: 当前已加载的分类规则 dict。
            ref_path_str: 当前文件的引用路径（用于解析 extends 相对路径）。
            context_path: 包含引用的 YAML 文件路径。

        Returns:
            沿继承链全量合并后的 dict（不含 extends 键）。

        Raises:
            FileNotFoundError: extends 指向的基文件不存在。
        """
        extends_ref: str | None = data.pop("extends", None)
        if extends_ref is None:
            return data

        # 解析当前文件的所在目录，extends 路径相对于此目录
        ref_path = self._resolve_ref_path(ref_path_str, context_path)
        if ref_path is None:
            return data  # 防御：不应到达这里
        base_dir = ref_path.parent

        base_path = (base_dir / extends_ref).resolve()
        if not base_path.is_file():
            raise FileNotFoundError(f"分类规则 extends 基文件不存在: {base_path}")

        base_data = self._load_yaml(base_path)

        # 构造基文件的引用路径，供递归解析使用
        config_root = self._config_root.resolve()
        base_ref_str = str(base_path.relative_to(config_root))
        base_data = self._resolve_extends(base_data, base_ref_str, context_path)

        return self._deep_merge_with_append(base_data, data)

    def _deep_merge_with_append(
        self, base: dict[str, Any], overlay: dict[str, Any]
    ) -> dict[str, Any]:
        """合并两个 dict：dict 键深层合并，list 键追加。

        与 ``_deep_merge`` 的区别：list 键不替换，而是 base + overlay 追加。

        Args:
            base: 基础配置。
            overlay: 覆盖配置（优先级更高，其 list 元素追加到末尾）。

        Returns:
            合并后的新 dict。
        """
        result: dict[str, Any] = dict(base)
        for key, val in overlay.items():
            if key not in result:
                result[key] = val
            elif isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = self._deep_merge_with_append(result[key], val)
            elif isinstance(result[key], list) and isinstance(val, list):
                result[key] = result[key] + val
            else:
                result[key] = val
        return result

    def _resolve_sandbox_ref(
        self,
        target_data: dict[str, Any],
        deployment_profile: dict[str, Any],
    ) -> str | None:
        """根据 deployment profile 解析实际 sandbox policy 引用。

        Deployment profile 的 ``sandbox.profile`` 优先于 target 的
        ``sandbox_profile_ref``，这样 ``NEWSSENTRY_PROFILE`` 能真实影响
        本次 bounded run 的权限边界。
        """
        sandbox_cfg = deployment_profile.get("sandbox", {})
        profile_ref = sandbox_cfg.get("profile") if isinstance(sandbox_cfg, dict) else None
        if isinstance(profile_ref, str) and profile_ref:
            if "/" in profile_ref or profile_ref.endswith(".yaml"):
                return profile_ref
            return f"config/sandbox/{profile_ref}.yaml"
        target_ref = target_data.get("sandbox_profile_ref")
        return str(target_ref) if target_ref is not None else None

    def _resolve_output_root(
        self,
        deployment_profile: dict[str, Any],
        output_root_override: str | Path | None,
        allow_external_output_root: bool,
    ) -> Path:
        """解析输出根目录并默认限制在项目内。

        相对路径总是以项目根目录为基准。绝对路径只有在调用方显式允许时
        才能位于项目外，避免开源模板误写用户主目录或系统目录。
        """
        paths = deployment_profile.get("paths", {})
        profile_output_root = paths.get("output_root") if isinstance(paths, dict) else None
        raw_root = output_root_override or profile_output_root or "./data"
        output_root = Path(raw_root).expanduser()
        if not output_root.is_absolute():
            output_root = self._config_root / output_root

        resolved = output_root.resolve()
        project_root = self._config_root.resolve()
        if not allow_external_output_root:
            try:
                resolved.relative_to(project_root)
            except ValueError as e:
                raise ValueError(
                    "输出根目录必须位于项目内；若确需项目外路径，请显式设置 "
                    "NEWSSENTRY_ALLOW_EXTERNAL_DATA_DIR=1"
                ) from e
        return resolved

    def _load_sources(
        self,
        target_id: str,
        source_ids: list[str],
        target_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """加载 target 的所有 source channel 配置。

        Args:
            target_id: target 标识符（如 "italy"）。
            source_ids: source channel ID 列表（如 ["ansa", "repubblica"]）。
            target_data: target 配置，用于给 source 注入默认语言。

        Returns:
            SourceChannel 数据列表（已校验）。
        """
        sources: list[dict[str, Any]] = []
        language_scope = (target_data or {}).get("language_scope", {})
        target_language = (
            language_scope.get("primary", "mixed") if isinstance(language_scope, dict) else "mixed"
        )
        for sid in source_ids:
            # 跳过社媒渠道配置 — 由 SocialKOLCollector 独立加载
            if sid.startswith("social/"):
                continue
            source_path = self._source_path_for_ref(target_id, sid)
            if not source_path.is_file():
                raise FileNotFoundError(f"Source 配置文件不存在: {source_path}")
            data = self._load_yaml(source_path)
            self._validate_resolved_schema(data, source_path)
            data["_source_ref"] = sid
            data["target_id"] = target_id
            data["language"] = str(data.get("language") or target_language or "mixed").lower()
            sources.append(data)
        return sources

    def _source_path_for_ref(self, target_id: str, source_ref: str) -> Path:
        """Resolve a target-local or shared source-pool ref to a YAML file."""
        ref = str(source_ref or "").replace("\\", "/").strip("/")
        if not ref or ".." in ref.split("/"):
            raise ValueError(f"非法 source ref: {source_ref}")
        if ref.startswith("pool:"):
            pool_ref = ref.removeprefix("pool:").strip("/")
            if not pool_ref or ".." in pool_ref.split("/"):
                raise ValueError(f"非法 source pool ref: {source_ref}")
            return self._config_root / "config" / "source-pools" / f"{pool_ref}.yaml"
        return self._config_root / "config" / "sources" / target_id / f"{ref}.yaml"


# ── country_axes 隔离验证 ─────────────────────────────────────


ITALY_SPECIFIC_AXES = {"coalition", "eu_role", "region", "china_italy_relations"}


def validate_country_axes_isolation(
    target_id: str,
    classification: dict[str, Any],
) -> None:
    """验证分类结果中的 country_axes 不包含意大利专有轴。

    在非意大利目标的 ClassifierRules.apply_to_event() 中调用，
    防止意大利专有轴泄漏到其他国家事件。

    Args:
        target_id: 当前目标 ID。
        classification: 事件分类结果 dict。

    Raises:
        ValueError: 非意大利目标包含意大利专有轴。
    """
    if target_id == "italy":
        return
    country_axes = classification.get("country_axes", {})
    for axis in ITALY_SPECIFIC_AXES:
        if axis in country_axes:
            raise ValueError(
                f"目标 '{target_id}' 的分类结果含意大利专有轴 '{axis}'，"
                f"请检查 config/country-axes/{target_id}.yaml"
            )
