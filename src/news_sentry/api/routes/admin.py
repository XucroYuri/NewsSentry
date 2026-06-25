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

    # ── Admin 总览 ──
    router.get("/api/v1/admin/overview")(h["admin_overview"])

    # ── 统计 ──
    router.get("/api/v1/stats", response_model=h.get("StatsResponse"))(h["get_stats"])
    router.get("/api/v1/stats/today", response_model=h.get("TodayStatsResponse"))(
        h["get_today_stats_api"]
    )
    router.get("/api/v1/events/top", response_model=h.get("TopEventsResponse"))(
        h["get_top_events_api"]
    )

    # ── 配置（非 target 相关）──
    router.get(
        "/api/v1/config/output/destinations",
        response_model=h.get("DestinationListResponse"),
    )(h["list_destinations"])
    router.get(
        "/api/v1/config/provider/routes",
        response_model=h.get("ProviderRoutesResponse"),
    )(h["get_provider_routes"])
    router.patch("/api/v1/config/output/destinations/{destination_id}")(
        h["update_destination_config"]
    )
    router.patch("/api/v1/config/provider/routes/{route_id}")(h["update_provider_route"])
    router.post("/api/v1/config/reload")(h["reload_config"])

    # ── 通知规则 (R1) ──
    router.get(
        "/api/v1/notification-rules",
        response_model=h.get("NotificationRuleListResponse"),
    )(h["list_notification_rules"])
    router.post("/api/v1/notification-rules")(h["upsert_notification_rule"])
    router.delete("/api/v1/notification-rules/{rule_id}")(h["delete_notification_rule"])

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
