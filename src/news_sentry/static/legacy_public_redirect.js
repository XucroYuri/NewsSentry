"use strict";

(function redirectLegacyPublicRoutes() {
  function encodeHashPart(value) {
    return encodeURIComponent(String(value || ""));
  }

  function safeDecodeHashParam(value) {
    try {
      return decodeURIComponent(value || "");
    } catch {
      return value || "";
    }
  }

  function splitHash(hash) {
    const raw = hash || "#/news/feed";
    const body = String(raw).replace(/^#/, "").replace(/^\//, "");
    return body.split("/").filter(Boolean);
  }

  function legacyPublicHref(hash) {
    const parts = splitHash(hash);
    const first = parts[0] || "news";
    if (first !== "news") return null;

    const second = parts[1] || "feed";
    if (second === "feed") return "/public-app/#/feed?channel=featured";

    if (second === "target") {
      const targetId = safeDecodeHashParam(parts[2] || "");
      if (!targetId) return "/public-app/#/feed?channel=featured";

      if (parts[3] === "events") {
        const eventId = safeDecodeHashParam(parts[4] || "");
        if (!eventId) return "/public-app/#/feed?channel=featured";
        const params = new URLSearchParams();
        params.set("target_id", targetId);
        return `/public-app/#/events/${encodeHashPart(eventId)}?${params.toString()}`;
      }

      if (parts[3] === "analysis") {
        const params = new URLSearchParams();
        params.set("target_id", targetId);
        const section = safeDecodeHashParam(parts[4] || "");
        if (section) params.set("section", section);
        return `/public-app/#/analysis?${params.toString()}`;
      }

      const params = new URLSearchParams();
      params.set("channel", "targets");
      params.set("target_id", targetId);
      const channelId = safeDecodeHashParam(parts[3] || "");
      if (channelId && channelId !== "all") params.set("category", channelId);
      return `/public-app/#/feed?${params.toString()}`;
    }

    if (second === "events" && parts[2]) {
      return `/public-app/#/events/${encodeHashPart(safeDecodeHashParam(parts[2] || ""))}`;
    }

    return "/public-app/#/feed?channel=featured";
  }

  const nextHref = legacyPublicHref(window.location.hash);
  if (nextHref) window.location.replace(nextHref);
})();
