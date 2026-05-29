"""Phase 17/24: Alert Pipeline — real-time alerting with tiered push.

Sends alerts when events meet configurable thresholds (news_value_score,
china_relevance, recommendation). Supports Feishu webhook, email (SMTP),
and Telegram bot. Includes 24h dedup to prevent alert fatigue.

Phase 24 adds tier-based push strategy:
  L1: 原文快报 (news_value_score >= 60)
  L2: 翻译快报 (news_value_score >= 80, auto-translate)
  L3: 突发稿件 (news_value_score >= 90 + breaking, translate + AI draft)
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from news_sentry.models.newsevent import (
    NewsEvent,
    PipelineStage,
)

logger = logging.getLogger(__name__)


class AlertPipeline:
    """告警管道 — 阈值过滤 + 去重 + 多通道推送。

    Attributes:
        _destinations: 启用的告警目标列表
        _dedup_window: 去重时间窗口（秒）
        _alerted: 已告警事件 ID → 时间戳映射
    """

    def __init__(
        self,
        destinations: list[dict[str, Any]],
        dedup_window_hours: int = 24,
        data_dir: Path | None = None,
        translate_fn: Callable[[str, str], str] | None = None,
        draft_fn: Callable[[str, str, str], str] | None = None,
    ) -> None:
        self._destinations = [d for d in destinations if d.get("enabled", False)]
        self._dedup_window = dedup_window_hours * 3600
        self._alerted: dict[str, float] = {}
        self._data_dir = data_dir or Path("./data")
        self._translate_fn = translate_fn
        self._draft_fn = draft_fn
        self._stats: dict[str, int] = {
            "total_checked": 0,
            "alerts_sent": 0,
            "alerts_deduped": 0,
            "alerts_failed": 0,
        }

    def process(self, events: list[NewsEvent], run_id: str) -> dict[str, int]:
        """处理事件列表，对满足条件的事件发送告警。

        Phase 24: 按 tier 级别分发不同格式的告警内容。
        L1 只推原文，L2 自动附加翻译，L3 附加翻译 + AI 草稿。

        Args:
            events: 已研判的事件列表。
            run_id: 本次运行标识。

        Returns:
            告警统计 dict。
        """
        for event in events:
            self._stats["total_checked"] += 1

            if not self._should_alert(event):
                continue

            if self._is_deduped(event):
                self._stats["alerts_deduped"] += 1
                continue

            for dest in self._destinations:
                if not self._matches_filter(event, dest.get("filter", {})):
                    continue

                # Phase 24: L2/L3 自动翻译
                tier = dest.get("tier", "")
                auto_translate = dest.get("auto_translate", tier in ("L2", "L3"))
                if auto_translate and not event.title_translated and self._translate_fn:
                    try:
                        event.title_translated = self._translate_fn(
                            event.title_original,
                            str(event.language.value) if hasattr(event.language, "value") else "en",
                        )
                    except Exception as exc:
                        logger.warning("自动翻译失败: event_id=%s error=%s", event.id, exc)

                # Phase 24: L3 AI 报道方案草稿
                auto_draft = dest.get("auto_draft", tier == "L3")
                if auto_draft and self._draft_fn and "editorial_draft" not in event.metadata:
                    try:
                        title = event.title_translated or event.title_original
                        draft = self._draft_fn(
                            title,
                            event.content_original[:500],
                            str(event.language.value) if hasattr(event.language, "value") else "en",
                        )
                        event.metadata["editorial_draft"] = draft
                    except Exception as exc:
                        logger.warning("草稿生成失败: event_id=%s error=%s", event.id, exc)

                try:
                    tier = dest.get("tier", "")
                    alert_body = self._format_tier_alert(event, run_id, tier)
                    self._send(dest, alert_body, event, run_id)
                    self._stats["alerts_sent"] += 1
                except Exception as e:
                    self._stats["alerts_failed"] += 1
                    logger.warning(
                        "告警发送失败: dest=%s event_id=%s error=%s",
                        dest.get("destination_id", "?"),
                        event.id,
                        e,
                    )

            self._mark_alerted(event)

        self._prune_dedup()
        return dict(self._stats)

    def _should_alert(self, event: NewsEvent) -> bool:
        """判断事件是否满足任意目标的告警条件。"""
        if not self._destinations:
            return False

        if event.pipeline_stage != PipelineStage.JUDGED:
            return False

        if event.judge_result is None:
            return False

        for dest in self._destinations:
            filt = dest.get("filter", {})
            if self._matches_filter(event, filt):
                return True

        return False

    def _matches_filter(self, event: NewsEvent, filt: dict[str, Any]) -> bool:
        """检查事件是否匹配过滤条件。"""
        min_nvs = filt.get("min_news_value_score", 0)
        if (event.news_value_score or 0) < min_nvs:
            return False

        min_cr = filt.get("min_china_relevance", 0)
        if (event.china_relevance or 0) < min_cr:
            return False

        allowed_recs = filt.get("recommendation", [])
        if allowed_recs:
            rec_value = event.judge_result.recommendation.value if event.judge_result else ""
            if rec_value not in allowed_recs:
                return False

        return True

    def _is_deduped(self, event: NewsEvent) -> bool:
        """检查事件是否在去重窗口内已告警。"""
        ts = self._alerted.get(event.id)
        if ts is None:
            return False
        return (time.time() - ts) < self._dedup_window

    def _mark_alerted(self, event: NewsEvent) -> None:
        """标记事件已告警。"""
        self._alerted[event.id] = time.time()

    def _prune_dedup(self) -> None:
        """清理过期的去重记录。"""
        now = time.time()
        expired = [k for k, v in self._alerted.items() if (now - v) >= self._dedup_window]
        for k in expired:
            del self._alerted[k]

    async def check_smart_alerts(
        self,
        store: Any,  # noqa: ANN401
        target_id: str,
    ) -> list[dict[str, Any]]:
        """检查智能告警条件，返回告警列表。

        三类告警:
          1. 链更新告警: followup + strength >= 0.7
          2. 趋势变化告警: rising + hotness >= 60
          3. 实体突增告警: 日提及 > 2x 7天日均
        """
        alerts: list[dict[str, Any]] = []
        now_str = datetime.now(UTC).isoformat()
        date_bucket = now_str[:10]

        # 1. 链更新告警
        try:
            links = await store.get_recent_links(target_id, hours=24)
            for link in links:
                if link["link_type"] == "followup" and link["strength"] >= 0.7:
                    title = link.get("title_original") or "未知事件"
                    chain_root_id = link["source_event_id"]
                    linked_event_id = link["target_event_id"]
                    link_type = link["link_type"]
                    alerts.append(
                        {
                            "type": "chain_update",
                            "alert_key": (
                                f"chain_update:{chain_root_id}:{linked_event_id}:{link_type}"
                            ),
                            "severity": "high",
                            "message": (
                                f'追踪链新增后续事件: "{title}" (强度: {link["strength"]:.2f})'
                            ),
                            "details": {
                                "chain_root_id": chain_root_id,
                                "linked_event_id": linked_event_id,
                                "strength": link["strength"],
                                "link_type": link_type,
                            },
                            "triggered_at": now_str,
                        }
                    )
        except Exception as exc:
            logger.warning("链更新告警检查失败: %s", exc)

        # 2. 趋势变化告警
        try:
            from news_sentry.skills.analysis.trend_analyzer import compute_topic_trends

            daily_counts = await store.get_topic_daily_counts(target_id, days=14)
            top_topics = await store.get_top_topics(target_id, days=14, limit=10)
            trends = compute_topic_trends(daily_counts, top_topics, total_days=14)
            for trend in trends:
                if trend.trend_direction == "rising" and trend.hotness >= 60:
                    alerts.append(
                        {
                            "type": "trend_rising",
                            "alert_key": f"trend_rising:{trend.topic}:{date_bucket}",
                            "severity": "medium",
                            "message": (
                                f'"{trend.topic}" 主题热度快速上升 '
                                f"(热度: {trend.hotness}, 近7天: {trend.current_count}次, "
                                f"前7天: {trend.prev_count}次)"
                            ),
                            "details": {
                                "topic": trend.topic,
                                "hotness": trend.hotness,
                                "current_count": trend.current_count,
                                "prev_count": trend.prev_count,
                            },
                            "triggered_at": now_str,
                        }
                    )
        except Exception as exc:
            logger.warning("趋势变化告警检查失败: %s", exc)

        # 3. 实体突增告警
        try:
            entities = await store.query_entities(
                target_id=target_id,
                min_mentions=2,
                limit=20,
            )
            for entity in entities:
                name = entity["canonical_name"]
                mentions = await store.get_entity_daily_mentions(name, target_id, days=7)
                if len(mentions) < 2:
                    continue
                today_count = mentions[-1]["count"]
                prev_counts = [m["count"] for m in mentions[:-1]]
                avg = sum(prev_counts) / len(prev_counts) if prev_counts else 0
                if avg > 0 and today_count > avg * 2:
                    alerts.append(
                        {
                            "type": "entity_spike",
                            "alert_key": f"entity_spike:{name}:{date_bucket}",
                            "severity": "medium",
                            "message": (
                                f'"{name}" 实体提及量突增 '
                                f"(今日: {today_count}次, 7天日均: {avg:.1f}次)"
                            ),
                            "details": {
                                "entity_name": name,
                                "today_count": today_count,
                                "avg_count": round(avg, 1),
                            },
                            "triggered_at": now_str,
                        }
                    )
        except Exception as exc:
            logger.warning("实体突增告警检查失败: %s", exc)

        # 持久化告警记录
        if alerts:
            try:
                await store.save_alert_history(target_id, alerts)
            except Exception:
                logger.debug("告警持久化失败，不影响告警检查")

        return alerts

    def _format_alert(self, event: NewsEvent, run_id: str) -> str:
        """格式化告警内容为 Markdown（无 tier 的默认格式）。"""
        return self._format_tier_alert(event, run_id, "")

    def _format_tier_alert(self, event: NewsEvent, run_id: str, tier: str) -> str:
        """Phase 24: 根据 tier 级别格式化不同内容的告警。

        L1: 原文标题 + 链接 + 评分（最快推送）
        L2: L1 + 中文翻译标题（auto_translate）
        L3: L2 + AI 报道方案草稿（auto_draft）
        无 tier: 保持原有完整格式
        """
        rec = event.judge_result.recommendation.value if event.judge_result else "unknown"
        nvs = event.news_value_score or 0
        title = event.title_original

        if not tier:
            # 无 tier 的传统格式
            return self._format_full_alert(event, run_id)

        tier_label = {"L1": "原文快报", "L2": "翻译快报", "L3": "突发稿件"}.get(tier, "告警")
        lines = [
            f"### 🚨 {tier_label}",
            "",
            f"**标题**: {title}",
            f"**新闻价值**: {nvs}/100",
        ]

        # L2+: 附加翻译标题
        if tier in ("L2", "L3") and event.title_translated:
            lines.append(f"**中文**: {event.title_translated}")

        # L3: 附加 AI 生成的报道方案
        if tier == "L3":
            draft = event.metadata.get("editorial_draft", "")
            if draft:
                lines.append(f"**报道方案**:\n{draft[:500]}")
            elif event.content_translated:
                lines.append(f"**摘要**: {event.content_translated[:200]}")

        lines.append(f"**来源**: {event.source_id}")
        lines.append(f"**推荐**: {rec}")

        if event.url:
            lines.append(f"**链接**: {event.url}")

        lines.extend(
            [
                "",
                "---",
                f"run_id: {run_id} | event_id: {event.id} | tier: {tier}",
            ]
        )

        return "\n".join(lines)

    def _format_full_alert(self, event: NewsEvent, run_id: str) -> str:
        """完整格式告警（无 tier 时使用）。"""
        rec = event.judge_result.recommendation.value if event.judge_result else "unknown"
        confidence = event.judge_result.confidence if event.judge_result else 0
        rationale = event.judge_result.rationale if event.judge_result else ""

        title = event.title_translated or event.title_original
        lines = [
            "### 🚨 News Sentry 告警",
            "",
            f"**标题**: {title}",
            f"**来源**: {event.source_id}",
            f"**推荐**: {rec} (置信度: {confidence}%)",
            f"**新闻价值**: {event.news_value_score or 0}/100",
            f"**本国关联**: {event.china_relevance or 0}/100",
            f"**情感**: {event.sentiment_score or 0:.1f}",
        ]

        if rationale:
            lines.append(f"**理由**: {rationale}")

        if event.url:
            lines.append(f"**链接**: {event.url}")

        lines.extend(
            [
                "",
                "---",
                f"run_id: {run_id} | event_id: {event.id}",
            ]
        )

        return "\n".join(lines)

    def _send(
        self,
        dest: dict[str, Any],
        body: str,
        event: NewsEvent,
        run_id: str,
    ) -> None:
        """发送告警到指定目标。"""
        dest_type = dest.get("type", "")

        if dest_type == "feishu_webhook":
            self._send_feishu(dest, body, event)
        elif dest_type == "email_smtp":
            self._send_email(dest, body, event)
        elif dest_type == "telegram_bot":
            self._send_telegram(dest, body, event)
        elif dest_type == "generic_webhook":
            self._send_generic_webhook(dest, body, event)
        else:
            logger.warning("未知告警类型: %s", dest_type)

    def _send_feishu(self, dest: dict[str, Any], body: str, event: NewsEvent) -> None:
        """发送飞书 Webhook 告警。"""
        url = self._resolve_env_var(dest.get("url", ""))
        if not url:
            logger.warning("飞书 Webhook URL 未配置，跳过")
            return

        title = event.title_translated or event.title_original
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": f"🚨 {title[:50]}",
                    },
                    "template": "red",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": body,
                    },
                ],
            },
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            if resp.status >= 300:
                logger.warning("飞书 Webhook 响应异常: status=%d", resp.status)

    def _send_email(self, dest: dict[str, Any], body: str, event: NewsEvent) -> None:
        """发送 SMTP 邮件告警。"""
        smtp_host = self._resolve_env_var(dest.get("smtp_host", ""))
        smtp_port = int(dest.get("smtp_port", 587))
        smtp_user = self._resolve_env_var(dest.get("smtp_user", ""))
        smtp_pass = self._resolve_env_var(dest.get("smtp_password", ""))
        from_addr = dest.get("from", smtp_user)
        to_addrs = dest.get("to", [])
        if isinstance(to_addrs, str):
            to_addrs = [to_addrs]

        if not smtp_host or not to_addrs:
            logger.warning("邮件告警配置不完整，跳过")
            return

        title = event.title_translated or event.title_original
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[News Sentry] {title[:60]}"
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)
        msg.attach(MIMEText(body, "plain", "utf-8"))

        use_tls = dest.get("use_tls", True)
        if use_tls:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_addrs, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(from_addr, to_addrs, msg.as_string())

    def _send_telegram(self, dest: dict[str, Any], body: str, event: NewsEvent) -> None:
        """发送 Telegram Bot 告警。"""
        token = self._resolve_env_var(dest.get("bot_token", ""))
        chat_id = self._resolve_env_var(dest.get("chat_id", ""))

        if not token or not chat_id:
            logger.warning("Telegram Bot 配置不完整，跳过")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": body,
            "parse_mode": "Markdown",
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            if resp.status >= 300:
                logger.warning("Telegram Bot 响应异常: status=%d", resp.status)

    def _send_generic_webhook(self, dest: dict[str, Any], body: str, event: NewsEvent) -> None:
        """发送通用 Webhook 告警（POST JSON 到指定 URL）。"""
        url = self._resolve_env_var(dest.get("url", ""))
        if not url:
            logger.warning("通用 Webhook URL 未配置，跳过")
            return

        payload = {
            "event_id": event.id,
            "title": event.title_translated or event.title_original,
            "news_value_score": event.news_value_score or 0,
            "china_relevance": event.china_relevance or 0,
            "source_id": event.source_id,
            "url": event.url or "",
            "body": body,
        }

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = Request(  # noqa: S310
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:  # noqa: S310
            if resp.status >= 300:
                logger.warning("通用 Webhook 响应异常: status=%d", resp.status)

    @staticmethod
    def _resolve_env_var(value: str) -> str:
        """解析 ${ENV_VAR} 格式的环境变量引用。"""
        if not value:
            return ""
        if value.startswith("${") and value.endswith("}"):
            env_name = value[2:-1]
            return os.environ.get(env_name, "")
        return value

    @property
    def stats(self) -> dict[str, int]:
        """返回告警统计。"""
        return dict(self._stats)
