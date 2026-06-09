/**
 * router.js — hash route parsing shared by app.js and tests.
 */
"use strict";

const ADMIN_SECTIONS = new Set(["home", "collection", "review", "ops", "advanced"]);
const TARGET_WORKBENCH_TABS = new Set([
  "overview",
  "profile",
  "sources",
  "social",
  "rules",
  "collection",
  "review",
  "canonical",
  "maintenance",
]);
const ADMIN_TABS = {
  home: new Set(["overview"]),
  collection: new Set(["control", "sources", "targets", "health"]),
  review: new Set(["queue", "feedback", "rules", "alerts"]),
  ops: new Set(["runs", "maintenance", "backup", "notifications"]),
  advanced: new Set(["filters", "outputs", "ai", "webhook", "api-key", "users", "account", "theme"]),
};
const LEGACY_ADMIN_SECTIONS = new Set(["news", "alerts", "feedback", "config", "settings"]);
const LEGACY_ADMIN_TABS = {
  ops: new Set(["status", "collector", "health", "history"]),
};
const BARE_NEWS_LEGACY_SECTIONS = new Set(["events", "entities", "chains", "trends"]);

function safeDecodeHashParam(value) {
  try {
    return decodeURIComponent(value || "");
  } catch {
    return value || "";
  }
}

function encodeHashPart(value) {
  return encodeURIComponent(String(value || ""));
}

function splitHash(hash) {
  const raw = hash || "#/news/feed";
  const body = String(raw).replace(/^#/, "").replace(/^\//, "");
  return body.split("/").filter(Boolean);
}

export function parseRouteHash(hash) {
  const parts = splitHash(hash);
  const first = parts[0] || "news";

  if (first === "connect") {
    return { name: "adminLogin", scope: "admin", section: "admin", tab: "login", param: "", parts };
  }

  if (first === "admin") {
    if ((parts[1] || "") === "login") {
      return { name: "adminLogin", scope: "admin", section: "admin", tab: "login", param: "", parts };
    }
    if (!parts[1]) {
      return { name: "adminTargets", scope: "admin", section: "targets", tab: "list", param: "", parts };
    }
    if ((parts[1] || "") === "targets") {
      const targetId = safeDecodeHashParam(parts[2] || "");
      if (!targetId) {
        return { name: "adminTargets", scope: "admin", section: "targets", tab: "list", param: "", parts };
      }
      const requestedTab = safeDecodeHashParam(parts[3] || "overview") || "overview";
      const tab = TARGET_WORKBENCH_TABS.has(requestedTab) ? requestedTab : "overview";
      const param = safeDecodeHashParam(parts[4] || "");
      return {
        name: "adminTargetWorkbench",
        type: "admin-target",
        scope: "admin",
        section: "targets",
        tab,
        param,
        targetId,
        parts,
      };
    }
    const section = parts[1] || "home";
    const tab = parts[2] || "";
    const param = safeDecodeHashParam(parts[3] || "");
    if (LEGACY_ADMIN_SECTIONS.has(section) || LEGACY_ADMIN_TABS[section]?.has(tab)) {
      return { name: "legacyProtected", scope: "legacy", section, tab, param, parts };
    }
    if (ADMIN_SECTIONS.has(section) && tab && ADMIN_TABS[section] && !ADMIN_TABS[section].has(tab)) {
      return { name: "legacyProtected", scope: "legacy", section, tab, param, parts };
    }
    return { name: "adminSection", scope: "admin", section, tab, param, parts };
  }

  if (first === "news") {
    const second = parts[1] || "feed";
    if (second === "feed") {
      return { name: "publicNewsHome", scope: "public", section: "news", tab: "feed", param: "", parts };
    }
    if (second === "target") {
      const targetId = safeDecodeHashParam(parts[2] || "");
      if (parts[3] === "analysis") {
        return {
          name: "publicTargetAnalysis",
          scope: "public",
          section: "news",
          tab: "analysis",
          param: targetId,
          targetId,
          analysisSection: safeDecodeHashParam(parts[4] || ""),
          parts,
        };
      }
      if (parts[3] === "events") {
        const eventId = safeDecodeHashParam(parts[4] || "");
        return {
          name: "publicTargetEventDetail",
          scope: "public",
          section: "news",
          tab: "targetEvent",
          param: eventId,
          targetId,
          eventId,
          parts,
        };
      }
      const channelId = safeDecodeHashParam(parts[3] || "all") || "all";
      return {
        name: "publicTargetFeed",
        scope: "public",
        section: "news",
        tab: "target",
        param: targetId,
        targetId,
        channelId,
        parts,
      };
    }
    if (second === "events" && parts[2]) {
      const eventId = safeDecodeHashParam(parts[2] || "");
      return {
        name: "publicLegacyEventDetail",
        scope: "public",
        section: "news",
        tab: "events",
        param: eventId,
        eventId,
        parts,
      };
    }
    return {
      name: "legacyProtected",
      scope: "legacy",
      section: "news",
      tab: second,
      param: safeDecodeHashParam(parts[2] || ""),
      parts,
    };
  }

  if (BARE_NEWS_LEGACY_SECTIONS.has(first)) {
    return {
      name: "legacyProtected",
      scope: "legacy",
      section: "news",
      tab: first,
      param: safeDecodeHashParam(parts[1] || ""),
      parts,
    };
  }

  if (ADMIN_SECTIONS.has(first)) {
    return {
      name: "legacyProtected",
      scope: "legacy",
      section: first,
      tab: parts[1] || "",
      param: safeDecodeHashParam(parts[2] || ""),
      parts,
    };
  }

  return {
    name: "legacyProtected",
    scope: "legacy",
    section: first,
    tab: parts[1] || "",
    param: safeDecodeHashParam(parts[2] || ""),
    parts,
  };
}

export function isAdminLoginRoute(route) {
  return route?.name === "adminLogin";
}

export function isLegacyProtectedRoute(route) {
  return route?.name === "legacyProtected";
}

export function isPublicRoute(route) {
  return route?.scope === "public" || isAdminLoginRoute(route);
}

export function legacyPublicRouteToPublicAppHref(hashOrRoute = "") {
  const route =
    typeof hashOrRoute === "string" || !hashOrRoute
      ? parseRouteHash(hashOrRoute || "#/news/feed")
      : hashOrRoute;
  const parts = route.parts || [];
  const first = parts[0] || "news";
  if (first !== "news") return null;

  if (route.name === "publicTargetEventDetail" && route.eventId) {
    const params = new URLSearchParams();
    if (route.targetId) params.set("target_id", route.targetId);
    const query = params.toString();
    return `/public-app/#/events/${encodeHashPart(route.eventId)}${query ? `?${query}` : ""}`;
  }

  if (route.name === "publicLegacyEventDetail" && route.eventId) {
    return `/public-app/#/events/${encodeHashPart(route.eventId)}`;
  }

  if (route.name === "publicTargetAnalysis" && route.targetId) {
    const params = new URLSearchParams();
    params.set("target_id", route.targetId);
    if (route.analysisSection) params.set("section", route.analysisSection);
    return `/public-app/#/analysis?${params.toString()}`;
  }

  if (route.name === "publicTargetFeed" && route.targetId) {
    const params = new URLSearchParams();
    params.set("channel", "targets");
    params.set("target_id", route.targetId);
    if (route.channelId && route.channelId !== "all") params.set("category", route.channelId);
    return `/public-app/#/feed?${params.toString()}`;
  }

  return "/public-app/#/feed?channel=featured";
}

export function adminHashForLegacyRoute(route) {
  if (!route || !route.section) return "#/admin/home/overview";
  const section = route.section;
  const tab = route.tab || (section === "news" ? "overview" : "");
  const detail = route.param ? `/${encodeHashPart(route.param)}` : "";

  const mapped = {
    news: {
      overview: "#/admin/home/overview",
      events: route.param ? `#/admin/review/queue${detail}` : "#/admin/review/queue",
      entities: "#/admin/advanced/filters",
      chains: "#/admin/review/queue",
      trends: "#/admin/home/overview",
    },
    events: { "": "#/admin/review/queue" },
    entities: { "": "#/admin/advanced/filters" },
    chains: { "": "#/admin/review/queue" },
    trends: { "": "#/admin/home/overview" },
    alerts: {
      live: "#/admin/review/alerts",
      history: "#/admin/review/alerts",
      rules: "#/admin/advanced/filters",
    },
    feedback: {
      records: "#/admin/review/feedback",
      optimize: "#/admin/review/rules",
    },
    ops: {
      status: "#/admin/collection/control",
      collector: "#/admin/collection/control",
      health: "#/admin/collection/health",
      history: "#/admin/ops/runs",
      maintenance: "#/admin/ops/maintenance",
    },
    config: {
      target: "#/admin/collection/targets",
      sources: "#/admin/collection/sources",
      filters: "#/admin/advanced/filters",
      output: "#/admin/advanced/outputs",
      ai: "#/admin/advanced/ai",
      routes: "#/admin/advanced/ai",
      webhooks: "#/admin/advanced/webhook",
    },
    settings: {
      password: "#/admin/advanced/account",
      users: "#/admin/advanced/users",
      apiKey: "#/admin/advanced/api-key",
      theme: "#/admin/advanced/theme",
      backup: "#/admin/ops/backup",
    },
  };
  return mapped[section]?.[tab] || mapped[section]?.[""] || "#/admin/home/overview";
}

export function targetWorkbenchHashForLegacyRoute(route, targetId = "") {
  if (!route || !route.section) return "#/admin/targets";
  const encodedTarget = encodeHashPart(targetId || "");
  const targetBase = encodedTarget ? `#/admin/targets/${encodedTarget}` : "#/admin/targets";
  const scoped = (tab) => encodedTarget ? `${targetBase}/${tab}` : "#/admin/targets";
  const section = route.section;
  const tab = route.tab || "";
  const map = {
    collection: {
      control: scoped("collection"),
      sources: scoped("sources"),
      targets: "#/admin/targets",
      health: "#/admin/collection/health",
    },
    review: {
      queue: scoped("review"),
      feedback: scoped("review"),
      rules: scoped("review"),
      alerts: scoped("review"),
    },
    ops: {
      runs: scoped("maintenance"),
      maintenance: scoped("maintenance"),
      backup: scoped("maintenance"),
      notifications: "#/admin/ops/notifications",
    },
    advanced: {
      filters: scoped("rules"),
      outputs: scoped("maintenance"),
      ai: "#/admin/advanced/ai",
      webhook: "#/admin/advanced/webhook",
      "api-key": "#/admin/advanced/api-key",
      users: "#/admin/advanced/users",
      account: "#/admin/advanced/account",
      theme: "#/admin/advanced/theme",
    },
    config: {
      target: "#/admin/targets",
      sources: scoped("sources"),
      filters: scoped("rules"),
    },
  };
  return map[section]?.[tab] || map[section]?.[""] || "";
}

export function normalizeAdminRoute(route, validTabs = []) {
  if (!route) return route;
  if (route.section === "ops" && route.tab && !route.param && !validTabs.includes(route.tab)) {
    return { ...route, tab: validTabs[0] || "status", param: route.tab };
  }
  return route;
}
