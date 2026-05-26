/**
 * router.js — hash route parsing shared by app.js and tests.
 */
"use strict";

const ADMIN_SECTIONS = new Set(["news", "alerts", "ops", "feedback", "config", "settings"]);
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
    if ((parts[1] || "login") === "login") {
      return { name: "adminLogin", scope: "admin", section: "admin", tab: "login", param: "", parts };
    }
    const section = parts[1] || "ops";
    const tab = parts[2] || "";
    const param = safeDecodeHashParam(parts[3] || "");
    return { name: "adminSection", scope: "admin", section, tab, param, parts };
  }

  if (first === "news") {
    const second = parts[1] || "feed";
    if (second === "feed") {
      return { name: "publicNewsHome", scope: "public", section: "news", tab: "feed", param: "", parts };
    }
    if (second === "target") {
      const targetId = safeDecodeHashParam(parts[2] || "");
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

export function adminHashForLegacyRoute(route) {
  if (!route || !route.section) return "#/admin/ops/status";
  const section = route.section;
  const tab = route.tab || (section === "news" ? "overview" : "");
  const chunks = ["#/admin", encodeHashPart(section)];
  if (tab) chunks.push(encodeHashPart(tab));
  if (route.param) chunks.push(encodeHashPart(route.param));
  return chunks.join("/");
}

export function normalizeAdminRoute(route, validTabs = []) {
  if (!route) return route;
  if (route.section === "ops" && route.tab && !route.param && !validTabs.includes(route.tab)) {
    return { ...route, tab: validTabs[0] || "status", param: route.tab };
  }
  return route;
}
