export const CHANNELS = [
  { id: "all", label: "全部", terms: [] },
  { id: "featured", label: "精选", terms: [] },
  { id: "policy", label: "政策", terms: ["politics", "policy", "regulation", "government", "diplomacy"] },
  { id: "industry", label: "产业", terms: ["industry", "business", "market", "investment", "company", "economy"] },
  { id: "tech", label: "技术", terms: ["technology", "model", "chip", "infrastructure", "research", "open-source"] },
  { id: "risk", label: "风险", terms: ["security", "safety", "risk", "conflict", "sanction", "supply-chain"] },
  { id: "china", label: "中国相关", terms: ["china", "chinese", "china-relations"] },
];

function tagText(value) {
  if (!value) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "object") {
    return String(value.code || value.name || value.label || value.title || "");
  }
  return "";
}

function lower(value) {
  return tagText(value).trim().toLowerCase();
}

function collectClassificationTerms(ev) {
  const terms = [];
  const classification = ev.classification || ev.metadata?.classification || {};
  if (classification.l0) terms.push(classification.l0);
  const l1 = classification.l1;
  if (Array.isArray(l1)) terms.push(...l1);
  else if (l1) terms.push(l1);
  return terms;
}

export function eventTerms(ev) {
  const terms = [
    ...(Array.isArray(ev.flat_tags) ? ev.flat_tags : []),
    ...(Array.isArray(ev.topic_tags) ? ev.topic_tags : []),
    ...collectClassificationTerms(ev),
  ];
  return terms.map(lower).filter(Boolean);
}

export function eventMatchesChannel(ev, channelId) {
  if (!channelId || channelId === "all") return true;
  const score = Number(ev.score ?? ev.news_value_score ?? ev.importance_score ?? 0);
  const recommendation = ev.recommendation || ev.ai_recommendation || ev.judge_result?.recommendation || "";
  if (channelId === "featured") {
    return score >= 70 || recommendation === "publish" || recommendation === "review";
  }
  if (channelId === "china" && Number(ev.china_relevance || 0) >= 50) {
    return true;
  }
  const channel = CHANNELS.find((item) => item.id === channelId);
  if (!channel) return true;
  const terms = eventTerms(ev);
  return channel.terms.some((term) => terms.includes(term));
}

export function eventMatchesSearch(ev, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    ev.display_title,
    ev.title_translated,
    ev.title_original,
    ev.source_display_name,
    ev.source_id,
    ev.summary,
    ev.ai_reason,
    ...eventTerms(ev),
  ].map((value) => String(value || "").toLowerCase());
  return haystack.some((value) => value.includes(q));
}

export function filterGroups(groups, { channelId = "all", query = "" } = {}) {
  return (groups || [])
    .map((group) => ({
      ...group,
      events: (group.events || []).filter(
        (ev) => eventMatchesChannel(ev, channelId) && eventMatchesSearch(ev, query),
      ),
    }))
    .filter((group) => group.events.length > 0);
}

export function countEvents(groups) {
  return (groups || []).reduce((sum, group) => sum + (group.events || []).length, 0);
}
