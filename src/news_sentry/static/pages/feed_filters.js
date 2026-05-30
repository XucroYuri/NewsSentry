const CHANNEL_TERM_MAP = {
  policy: [
    "politics",
    "policy",
    "regulation",
    "government",
    "diplomacy",
    "parliament",
    "cabinet",
    "coalition",
    "eu-affairs",
    "migration-policy",
    "justice-reform",
    "govt_coalition",
  ],
  industry: [
    "industry",
    "business",
    "market",
    "investment",
    "company",
    "economy",
    "economic",
    "economics",
    "trade",
    "energy",
    "labor-market",
    "financial-markets",
    "corporate",
    "environment",
    "energy-transition",
    "environment_energy",
    "energy_transition",
    "labor_market",
  ],
  tech: [
    "tech",
    "technology",
    "ai",
    "semiconductor",
    "digital-policy",
    "cybersecurity",
    "research",
    "tech-industry",
    "digital",
    "model",
    "chip",
    "infrastructure",
    "open-source",
  ],
  risk: [
    "international-relations",
    "public-safety",
    "disaster",
    "sanctions",
    "russia-ukraine",
    "nato",
    "terrorism",
    "security",
    "international",
    "safety",
    "risk",
    "conflict",
    "sanction",
    "supply-chain",
    "supply_chain",
    "defense",
    "military",
  ],
  china: [
    "china-related",
    "china-italy-bilateral",
    "bri-italy",
    "chinese-investment",
    "china-eu-policy",
    "chinese-community",
    "china",
    "chinese",
    "china-relations",
    "china_italy_bilateral",
    "bri_italy",
    "trade_china_italy",
  ],
  society: [
    "society",
    "health",
    "education",
    "labor",
    "welfare",
    "housing",
    "immigration",
    "demographics",
    "culture-society",
    "culture_society",
  ],
  environment: [
    "environment",
    "environment-energy",
    "environment_energy",
    "energy-transition",
    "energy_transition",
    "climate",
    "weather",
    "disaster",
    "agriculture",
  ],
  international: [
    "international-relations",
    "international",
    "diplomacy",
    "eu-affairs",
    "nato",
    "sanctions",
    "war",
    "ukraine",
    "middle-east",
    "foreign-policy",
  ],
  culture: [
    "culture",
    "religion",
    "vatican",
    "heritage",
    "media",
    "sports",
    "entertainment",
    "tourism",
  ],
};

const CANONICAL_TERM_ALIASES = {
  economics: "economy",
  security: "public-safety",
  international: "international-relations",
  culture_society: "society",
  environment_energy: "environment",
  china_related: "china-related",
  political: "politics",
  technology: "tech",
  energy_transition: "energy-transition",
  environment_energy: "environment",
  culture_society: "society",
};

export const CHANNELS = [
  { id: "all", label: "全部", terms: [] },
  { id: "featured", label: "精选", terms: [] },
  {
    id: "policy",
    label: "政策",
    terms: CHANNEL_TERM_MAP.policy,
  },
  {
    id: "industry",
    label: "产业",
    terms: CHANNEL_TERM_MAP.industry,
  },
  {
    id: "tech",
    label: "技术",
    terms: CHANNEL_TERM_MAP.tech,
  },
  {
    id: "risk",
    label: "风险",
    terms: CHANNEL_TERM_MAP.risk,
    textTerms: [
      "attack",
      "attacc",
      "conflict",
      "crisi",
      "crisis",
      "guerra",
      "iran",
      "missile",
      "nuclear",
      "sanzion",
      "sanction",
      "ucraina",
      "ukraine",
    ],
  },
  {
    id: "society",
    label: "社会民生",
    terms: CHANNEL_TERM_MAP.society,
  },
  {
    id: "environment",
    label: "环境能源",
    terms: CHANNEL_TERM_MAP.environment,
  },
  {
    id: "international",
    label: "国际外交",
    terms: CHANNEL_TERM_MAP.international,
  },
  {
    id: "culture",
    label: "文化社会",
    terms: CHANNEL_TERM_MAP.culture,
  },
  {
    id: "clusters",
    label: "聚类线索",
    terms: [],
  },
  { id: "china", label: "中国相关", terms: CHANNEL_TERM_MAP.china },
];

const CHINA_TEXT_TERMS = ["china", "chinese", "cina", "cinese", "pechino", "beijing", "中国"];

function tagText(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "object") {
    const tagValue = [value.code, value.name, value.label, value.title].find(
      (item) => item !== null && item !== undefined && item !== "",
    );
    return tagValue === undefined ? "" : String(tagValue);
  }
  return "";
}

function lower(value) {
  return tagText(value).trim().toLowerCase();
}

function canonicalTerm(value) {
  const text = lower(value);
  return CANONICAL_TERM_ALIASES[text] || text;
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
  return terms.map(canonicalTerm).filter(Boolean);
}

function eventText(ev) {
  return [
    ev.display_title,
    ev.title,
    ev.title_translated,
    ev.title_original,
    ev.summary,
    ev.ai_reason,
  ].map((value) => String(value || "").toLowerCase()).join(" ");
}

export function eventMatchesChannel(ev, channelId) {
  if (!channelId || channelId === "all") return true;
  const score = Number(ev.score ?? ev.news_value_score ?? ev.importance_score ?? 0);
  const recommendation = ev.recommendation || ev.ai_recommendation || ev.judge_result?.recommendation || "";
  if (channelId === "featured") {
    return score >= 70 || recommendation === "publish" || recommendation === "review";
  }
  if (channelId === "clusters") {
    const clusterSize = Number(ev.clustering?.cluster_size || ev.metadata?.clustering?.cluster_size || 0);
    const clusterType = ev.clustering?.cluster_type || ev.metadata?.clustering?.cluster_type || "";
    return Boolean(ev.story_id || ev.cluster_id) && (clusterSize > 1 || clusterType === "same_event" || clusterType === "storyline");
  }
  if (channelId === "china" && Number(ev.china_relevance || 0) >= 50) {
    return true;
  }
  const channel = CHANNELS.find((item) => item.id === channelId);
  if (!channel) return false;
  const terms = eventTerms(ev);
  if (channelId === "china" && CHINA_TEXT_TERMS.some((term) => eventText(ev).includes(term))) {
    return true;
  }
  if (channel.terms.some((term) => terms.includes(term))) {
    return true;
  }
  const text = eventText(ev);
  return Array.isArray(channel.textTerms) && channel.textTerms.some((term) => text.includes(term));
}

export function eventMatchesSearch(ev, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    ev.id,
    ev.event_id,
    ev.display_title,
    ev.title,
    ev.title_translated,
    ev.title_original,
    ev.source_display_name,
    ev.source_name,
    ev.source,
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

export function channelsWithCounts(
  groups,
  { currentChannel = "all", includeEmpty = false, maxSecondaryChannels = null } = {},
) {
  const countedChannels = CHANNELS.map((channel) => {
    const channelGroups = filterGroups(groups, { channelId: channel.id, query: "" });
    return { ...channel, count: countEvents(channelGroups) };
  });
  const visibleChannels = countedChannels.filter((channel) => (
    includeEmpty
    || channel.id === "all"
    || channel.id === "featured"
    || channel.id === currentChannel
    || channel.count > 0
  ));
  if (!Number.isFinite(Number(maxSecondaryChannels)) || Number(maxSecondaryChannels) <= 0) {
    return visibleChannels;
  }
  const fixed = visibleChannels.filter((channel) => channel.id === "all" || channel.id === "featured");
  const rest = visibleChannels.filter((channel) => channel.id !== "all" && channel.id !== "featured");
  const current = rest.find((channel) => channel.id === currentChannel);
  const ranked = rest
    .filter((channel) => channel.id !== currentChannel)
    .sort((a, b) => (b.count - a.count) || (CHANNELS.findIndex((item) => item.id === a.id) - CHANNELS.findIndex((item) => item.id === b.id)))
    .slice(0, Number(maxSecondaryChannels));
  const merged = [...fixed, ...ranked];
  if (current && !merged.some((channel) => channel.id === current.id)) {
    merged.push(current);
  }
  return merged.sort((a, b) => CHANNELS.findIndex((item) => item.id === a.id) - CHANNELS.findIndex((item) => item.id === b.id));
}
