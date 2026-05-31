"""Markdown export projections.

Markdown is an explicit export format, not canonical storage.
"""

from __future__ import annotations

from typing import Any

import yaml

from news_sentry.models.newsevent import NewsEvent
from news_sentry.skills.output.markdown_writer import MarkdownWriter


def render_news_event_markdown(event: NewsEvent) -> str:
    """Render one NewsEvent as downloadable Markdown without filesystem writes."""
    writer = MarkdownWriter(
        {
            "target_id": getattr(event, "target_id", None) or "default",
            "output_base_dir": ".",
            "translation_heading": "中文译文",
        }
    )
    return writer.render(event)


def render_canonical_event_markdown(
    event: dict[str, Any],
    mentions: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
) -> str:
    """Render a canonical event evidence package as Markdown."""
    frontmatter = {
        "canonical_event_id": event.get("canonical_event_id"),
        "target_id": event.get("target_id"),
        "news_value_score": event.get("news_value_score"),
        "china_relevance": event.get("china_relevance"),
        "mention_count": len(mentions),
        "relation_count": len(relations),
        "artifact_count": len(artifacts),
        "export_kind": "canonical_event_evidence_package",
    }
    fm = yaml.dump(
        {key: value for key, value in frontmatter.items() if value is not None},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip("\n")

    title = str(event.get("title") or event.get("primary_title") or event["canonical_event_id"])
    summary = str(event.get("summary") or event.get("primary_summary") or "")
    lines = [
        "---",
        fm,
        "---",
        "",
        f"# {title}",
        "",
    ]
    if summary:
        lines.extend([summary, ""])

    lines.extend(["## 信源报道", ""])
    if mentions:
        for mention in mentions:
            mention_title = (
                mention.get("title") or mention.get("title_original") or mention["mention_id"]
            )
            lines.append(f"- **{mention.get('source_id') or 'unknown'}** | {mention_title}")
            if mention.get("published_at"):
                lines.append(f"  - 发布时间: {mention['published_at']}")
            if mention.get("url"):
                lines.append(f"  - 链接: {mention['url']}")
            file_path = (mention.get("metadata") or {}).get("file_path")
            if file_path:
                lines.append(f"  - 历史文件: `{file_path}`")
    else:
        lines.append("暂无信源报道。")

    lines.extend(["", "## 事件关系", ""])
    if relations:
        for relation in relations:
            relation_type = relation.get("relation_type", "related")
            source_id = relation.get("source_canonical_event_id")
            target_id = relation.get("target_canonical_event_id")
            lines.append(f"- {relation_type} | {source_id} -> {target_id}")
    else:
        lines.append("暂无事件关系。")

    lines.extend(["", "## 研究记录", ""])
    if artifacts:
        for artifact in artifacts:
            artifact_label = artifact.get("title") or artifact.get("artifact_id")
            lines.append(f"- **{artifact.get('artifact_type')}**: {artifact_label}")
    else:
        lines.append("暂无研究记录。")

    return "\n".join(lines).rstrip() + "\n"
