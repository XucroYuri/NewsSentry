"""Phase 5: Provider routing configuration models.

Implements: docs/spec/phase-5-ai-provider-routing.md
Schema: schemas/providerconfig.schema.json
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderRoute(BaseModel):
    """单条 AI 路由定义，对应 config/provider/routes.yaml 中的一条 route 条目。

    route_id 唯一标识一条路由；task_type 用于按任务类型匹配路由。
    未显式指定的 fallback_route_ids 默认为空列表。
    """

    route_id: str
    task_type: str
    provider: str
    model: str
    model_env_var: str | None = None
    model_pool: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(ge=1)
    max_cost_usd_per_call: float = Field(ge=0.0)
    output_schema_ref: str | None = None
    audit: bool = False
    notes: str | None = None
    fallback_route_ids: list[str] = Field(default_factory=list)


class ProviderRoutesConfig(BaseModel):
    """路由配置顶层容器，映射 config/provider/routes.yaml 的完整结构。

    routes_version 通过 YAML 头部声明，用于配置迁移检测。
    fallback_route_id 是所有路由失败时的最终回退路由。
    """

    routes_version: str
    routes: list[ProviderRoute]
    fallback_route_id: str
