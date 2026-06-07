/**
 * target_groups.js — 公开首页与后台目标工作台共享的 target 分组口径。
 */
"use strict";

export const TARGET_KIND_ORDER = ["topic", "country", "other"];

export const TARGET_KIND_LABELS = {
  topic: "专题监控目标",
  country: "国别监控目标",
  other: "其他监控目标",
};

const TARGET_KIND_ALIASES = {
  topic: "topic",
  "topic-target": "topic",
  theme: "topic",
  subject: "topic",
  "special-topic": "topic",
  country: "country",
  "country-target": "country",
  nation: "country",
  "country-monitoring": "country",
};

export function normalizeTargetKind(target = {}) {
  const raw = target.monitoring_type || target.target_type || target.kind || "";
  const normalized = String(raw).trim().toLowerCase().replaceAll("_", "-");
  if (TARGET_KIND_ALIASES[normalized]) return TARGET_KIND_ALIASES[normalized];
  const targetId = String(target.target_id || "").trim().toLowerCase();
  if (targetId === "china-watch-en" || targetId.startsWith("china-watch") || target.topic_label) {
    return "topic";
  }
  return "country";
}

export function targetKindLabel(target = {}) {
  const kind = normalizeTargetKind(target);
  return target.monitoring_label || TARGET_KIND_LABELS[kind] || TARGET_KIND_LABELS.other;
}

export function targetTopicLabel(target = {}) {
  const explicit = target.topic_label || target.monitoring_topic || target.topic_name || "";
  if (String(explicit).trim()) return String(explicit).trim();
  return String(target.target_id || "").trim().toLowerCase() === "china-watch-en" ? "涉中舆情" : "";
}

function sortTargets(targets) {
  return [...targets].sort((a, b) => {
    const byEvents = Number(b.event_count || 0) - Number(a.event_count || 0);
    if (byEvents !== 0) return byEvents;
    return String(a.display_name || a.target_id || "").localeCompare(String(b.display_name || b.target_id || ""));
  });
}

export function groupTargetsByKind(targets = []) {
  const grouped = new Map(TARGET_KIND_ORDER.map((kind) => [kind, []]));
  for (const target of targets) {
    const kind = normalizeTargetKind(target);
    const key = TARGET_KIND_ORDER.includes(kind) ? kind : "other";
    grouped.get(key).push(target);
  }
  return TARGET_KIND_ORDER
    .map((kind) => ({
      id: kind,
      label: TARGET_KIND_LABELS[kind],
      targets: sortTargets(grouped.get(kind) || []),
    }))
    .filter((group) => group.targets.length > 0);
}

