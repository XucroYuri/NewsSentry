"""Admin API routes — authentication required.

Uses a ``register_admin_routes`` function that accepts a router and handler dict
so that handler closures defined in ``create_app()`` can be wired to routes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter


def register_admin_routes(router: APIRouter, h: dict[str, Any]) -> None:
    """Register all admin (auth-required) routes on the given APIRouter."""

    # ── 指标 / 运行时 ──
    router.get("/api/v1/metrics", include_in_schema=False)(h["prometheus_metrics"])
    router.get("/api/v1/runtime/info", include_in_schema=False)(h["runtime_info"])

    # ── 采集器 ──
    router.get("/api/v1/collector/status")(h["collector_status"])
    router.get("/api/v1/collector/config")(h["collector_config"])
    router.put("/api/v1/collector/config")(h["update_collector_config"])
    router.post("/api/v1/collector/start")(h["start_collector"])
    router.post("/api/v1/collector/stop")(h["stop_collector"])
    router.get("/api/v1/collector/diagnostics")(h["collector_diagnostics"])

    # ── AI 增强 ──
    router.get("/api/v1/ai/enrichment/status")(h["ai_enrichment_status"])
    router.put("/api/v1/ai/enrichment/config")(h["update_ai_enrichment_config"])
    router.post("/api/v1/ai/enrichment/run")(h["run_ai_enrichment"])
    router.get("/api/v1/ai/translation/status")(h["public_translation_status"])
    router.put("/api/v1/ai/translation/config")(h["update_public_translation_config"])
    router.post("/api/v1/ai/translation/run")(h["run_public_translation"])

    # ── 数据状态 ──
    router.get("/api/v1/status")(h["data_status"])

    # ── 认证（管理）──
    router.post("/api/v1/auth/stream-token")(h["auth_stream_token"])
    router.get("/api/v1/auth/me")(h["auth_me"])
    router.post("/api/v1/auth/change-password")(h["auth_change_password"])

    # ── 用户管理 ──
    router.get("/api/v1/admin/users")(h["admin_list_users"])
    router.post("/api/v1/admin/users")(h["admin_create_user"])
    router.delete("/api/v1/admin/users/{username}")(h["admin_delete_user"])
    router.post("/api/v1/admin/users/{username}/reset-password")(h["admin_reset_password"])

    # ── 设置 ──
    router.get("/api/v1/settings/api-key")(h["get_api_key_setting"])
    router.put("/api/v1/settings/api-key")(h["set_api_key_setting"])
    router.delete("/api/v1/settings/api-key")(h["delete_api_key_setting"])
    router.get("/api/v1/settings/notifications")(h["get_notifications"])
    router.put("/api/v1/settings/notifications")(h["update_notifications"])

    # ── 简报 ──
    router.post("/api/v1/briefing/send")(h["send_briefing"])

    # ── Admin Target 管理 ──
    router.get("/api/v1/admin/targets")(h["list_admin_targets"])
    router.post("/api/v1/admin/targets")(h["create_admin_target"])
    router.patch("/api/v1/admin/targets/{target_id}")(h["patch_admin_target"])
    router.post("/api/v1/admin/targets/{target_id}/archive")(h["archive_admin_target"])
    router.post("/api/v1/admin/targets/{target_id}/restore")(h["restore_admin_target"])
    router.get("/api/v1/admin/targets/{target_id}/overview")(h["admin_target_overview"])
    router.post("/api/v1/admin/targets/{target_id}/validate")(h["validate_admin_target"])
    router.get("/api/v1/admin/targets/{target_id}/inventory")(h["admin_target_inventory"])
    router.get("/api/v1/admin/targets/{target_id}/sources")(h["list_admin_target_sources"])
    router.post("/api/v1/admin/targets/{target_id}/sources")(h["create_admin_target_source"])
    router.patch("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}")(
        h["patch_admin_target_source"]
    )
    router.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/archive")(
        h["archive_admin_target_source"]
    )
    router.post("/api/v1/admin/targets/{target_id}/sources/{source_ref:path}/restore")(
        h["restore_admin_target_source"]
    )
    router.get("/api/v1/admin/targets/{target_id}/social")(h["get_admin_target_social"])
    router.post("/api/v1/admin/targets/{target_id}/social/dimensions")(
        h["create_admin_social_dimension"]
    )
    router.patch("/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}")(
        h["patch_admin_social_dimension"]
    )
    router.post(
        "/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts"
    )(h["create_admin_social_account"])
    router.patch(
        "/api/v1/admin/targets/{target_id}/social/dimensions/{dimension}/accounts/{handle}"
    )(h["patch_admin_social_account"])
    router.get("/api/v1/admin/overview")(h["admin_overview"])

    # ── 统计 ──
    router.get("/api/v1/stats", response_model=h.get("StatsResponse"))(h["get_stats"])
    router.get("/api/v1/stats/today", response_model=h.get("TodayStatsResponse"))(
        h["get_today_stats_api"]
    )
    router.get("/api/v1/events/top", response_model=h.get("TopEventsResponse"))(
        h["get_top_events_api"]
    )

    # ── 配置 ──
    router.get("/api/v1/config/targets/{target_id}")(h["get_target_config"])
    router.get(
        "/api/v1/config/targets/{target_id}/sources",
        response_model=h.get("SourceListResponse"),
    )(h["list_sources"])
    router.get("/api/v1/config/targets/{target_id}/sources/{source_id:path}")(
        h["get_source_config"]
    )
    router.get(
        "/api/v1/config/targets/{target_id}/filters",
        response_model=h.get("FilterRulesResponse"),
    )(h["get_filter_rules"])
    router.get(
        "/api/v1/config/output/destinations",
        response_model=h.get("DestinationListResponse"),
    )(h["list_destinations"])
    router.get(
        "/api/v1/config/provider/routes",
        response_model=h.get("ProviderRoutesResponse"),
    )(h["get_provider_routes"])
    router.put("/api/v1/config/targets/{target_id}")(h["update_target_config"])
    router.patch("/api/v1/config/targets/{target_id}/sources/{source_id:path}")(
        h["update_source_config"]
    )
    router.patch("/api/v1/config/targets/{target_id}/filters")(h["update_filter_config"])
    router.patch("/api/v1/config/output/destinations/{destination_id}")(
        h["update_destination_config"]
    )
    router.patch("/api/v1/config/provider/routes/{route_id}")(h["update_provider_route"])
    router.post("/api/v1/config/reload")(h["reload_config"])

    # ── 实体 ──
    router.get("/api/v1/entities", response_model=h.get("EntityListResponse"))(h["list_entities"])
    router.get(
        "/api/v1/entities/{entity_id}",
        response_model=h.get("EntityDetailResponse"),
    )(h["get_entity"])
    router.get(
        "/api/v1/entities/{entity_id}/events",
    )(h["get_entity_events"])
    router.get(
        "/api/v1/entities/search",
    )(h["search_entities"])
    router.post(
        "/api/v1/entities/merge",
        response_model=h.get("EntityMergeResponse"),
    )(h["merge_entities"])

    # ── Webhook / 导入 ──
    router.post("/api/v1/webhook", response_model=h.get("WebhookResponse"))(h["receive_webhook"])
    router.post("/api/v1/events/import", response_model=h.get("ImportResponse"))(h["import_events"])

    # ── 事件过渡 ──
    router.post("/api/v1/admin/events/{event_id}/transition")(h["transition_event_stage"])

    # ── 运行 ──
    router.get("/api/v1/runs", response_model=h.get("RunListResponse"))(h["list_runs"])
    router.get(
        "/api/v1/runs/active", response_model=h.get("HeartbeatResponse")
    )(h["get_active_run"])
    router.get("/api/v1/runs/{run_id:path}", response_model=h.get("RunDetailResponse"))(
        h["get_run_detail"]
    )
    router.get(
        "/api/v1/sources/health",
        response_model=h.get("SourceHealthListResponse"),
    )(h["list_source_health"])
    router.post("/api/v1/runs/trigger", response_model=h.get("TriggerResponse"))(h["trigger_run"])

    # ── 事件链接 ──
    router.get(
        "/api/v1/events/{event_id}/links",
        response_model=h.get("EventLinksResponse"),
    )(h["get_event_links"])
    router.get(
        "/api/v1/events/{event_id}/chain",
        response_model=h.get("EventChainResponse"),
    )(h["get_event_chain"])

    # ── 追踪链 ──
    router.get("/api/v1/chains", response_model=h.get("ChainListResponse"))(h["list_chains"])
    router.get(
        "/api/v1/chains/{root_id}/narrative",
        response_model=h.get("NarrativeResponse"),
    )(h["get_chain_narrative"])
    router.post(
        "/api/v1/chains/{root_id}/narrative",
        response_model=h.get("NarrativeResponse"),
    )(h["regenerate_chain_narrative"])

    # ── 趋势 ──
    router.get("/api/v1/trends/topics", response_model=h.get("TopicTrendsResponse"))(
        h["get_topic_trends"]
    )
    router.get(
        "/api/v1/trends/sentiment",
        response_model=h.get("SentimentTrendsResponse"),
    )(h["get_sentiment_trends"])

    # ── 告警 ──
    router.get("/api/v1/alerts/smart", response_model=h.get("SmartAlertsResponse"))(
        h["get_smart_alerts"]
    )
    router.get("/api/v1/alerts/history", response_model=h.get("AlertHistoryResponse"))(
        h["alert_history"]
    )

    # ── 规范化事件 ──
    router.get("/api/v1/canonical/diagnostics")(h["canonical_diagnostics"])
    router.post("/api/v1/canonical/backfill")(h["canonical_backfill"])
    router.get("/api/v1/canonical/events")(h["list_canonical_events"])
    router.get("/api/v1/canonical/events/{canonical_event_id}")(h["get_canonical_event"])
    router.get("/api/v1/canonical/events/{canonical_event_id}/mentions")(
        h["list_canonical_event_mentions"]
    )
    router.get("/api/v1/canonical/events/{canonical_event_id}/relations")(
        h["list_canonical_event_relations"]
    )
    router.get("/api/v1/canonical/events/{canonical_event_id}/export/markdown")(
        h["export_canonical_event_markdown"]
    )

    # ── 研究 ──
    router.get("/api/v1/research/queue")(h["research_queue"])
    router.post("/api/v1/research/graph/merge")(h["research_graph_merge"])
    router.post("/api/v1/research/graph/split")(h["research_graph_split"])
    router.get("/api/v1/research/graph/operations")(h["research_graph_operations"])
    router.get("/api/v1/research/events/{canonical_event_id}")(h["research_event_detail"])
    router.post("/api/v1/research/artifacts")(h["create_research_artifact"])
    router.patch("/api/v1/research/artifacts/{artifact_id}")(h["patch_research_artifact"])

    # ── 维护 ──
    router.get("/api/v1/maintenance/draft-diagnostics")(h["maintenance_draft_diagnostics"])
    router.post("/api/v1/maintenance/archive-duplicate-drafts")(
        h["maintenance_archive_duplicate_drafts"]
    )
    router.post("/api/v1/maintenance/prune", response_model=h.get("PruneResponse"))(
        h["maintenance_prune"]
    )
    router.post(
        "/api/v1/maintenance/backup",
        response_model=h.get("BackupResponse"),
    )(h["maintenance_backup"])
    router.get("/api/v1/maintenance/backups")(h["list_backups"])
    router.post("/api/v1/maintenance/restore")(h["restore_backup"])

    # ── 反馈 ──
    router.post("/api/v1/feedback", response_model=h.get("FeedbackSubmitResponse"))(
        h["submit_feedback"]
    )
    router.get("/api/v1/feedback", response_model=h.get("FeedbackListResponse"))(h["list_feedback"])
    router.get("/api/v1/feedback/stats", response_model=h.get("FeedbackStatsResponse"))(
        h["feedback_stats"]
    )

    # ── 规则优化 ──
    router.post(
        "/api/v1/rules/optimize",
        response_model=h.get("RulesOptimizeResponse"),
    )(h["optimize_rules"])
