"""Phase 17: Alert Pipeline — real-time alerting from judged events.

Sends alerts when events meet configurable thresholds (news_value_score,
china_relevance, recommendation). Supports Feishu webhook, email (SMTP),
and Telegram bot. Includes 24h dedup to prevent alert fatigue.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
import time
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
    ) -> None:
        self._destinations = [d for d in destinations if d.get("enabled", False)]
        self._dedup_window = dedup_window_hours * 3600
        self._alerted: dict[str, float] = {}
        self._data_dir = data_dir or Path("./data")
        self._stats: dict[str, int] = {
            "total_checked": 0,
            "alerts_sent": 0,
            "alerts_deduped": 0,
            "alerts_failed": 0,
        }

    def process(self, events: list[NewsEvent], run_id: str) -> dict[str, int]:
        """处理事件列表，对满足条件的事件发送告警。

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

            alert_body = self._format_alert(event, run_id)

            for dest in self._destinations:
                try:
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

    def _format_alert(self, event: NewsEvent, run_id: str) -> str:
        """格式化告警内容为 Markdown。"""
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
            f"**中国关联**: {event.china_relevance or 0}/100",
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
