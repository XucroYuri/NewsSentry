"""Config Pydantic models — ResolvedConfig per ADR-0014, ADR-0015."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
