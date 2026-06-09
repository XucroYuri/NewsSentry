/**
 * public_portal.js — small pure helpers for public news routes.
 */
"use strict";

function encodeHashPart(value) {
  return encodeURIComponent(String(value || ""));
}

export function targetPortalHref(targetId) {
  return `#/news/target/${encodeHashPart(targetId)}`;
}

export function targetAnalysisHref(targetId) {
  return `${targetPortalHref(targetId)}/analysis`;
}

export function targetAnalysisSectionHref(targetId, sectionId) {
  return `${targetAnalysisHref(targetId)}/${encodeHashPart(sectionId)}`;
}

export function channelPortalHref(targetId, channelId) {
  const base = targetPortalHref(targetId);
  return !channelId || channelId === "all" ? base : `${base}/${encodeHashPart(channelId)}`;
}

export function targetEventHref(targetId, eventId) {
  const encodedEvent = encodeHashPart(eventId);
  if (!targetId) return `#/news/events/${encodedEvent}`;
  return `${targetPortalHref(targetId)}/events/${encodedEvent}`;
}

export function adminEventHref(eventId) {
  return `#/admin/review/queue/${encodeHashPart(eventId)}`;
}

export function renderPublicBottomNav(targetId = "", active = "targets") {
  const hasTarget = Boolean(targetId);
  const feedHref = hasTarget ? targetPortalHref(targetId) : "#/news/feed";
  const analysisHref = hasTarget ? targetAnalysisHref(targetId) : "#/news/feed";
  const entitiesHref = hasTarget ? targetAnalysisSectionHref(targetId, "entities") : "#/news/feed";
  const item = (id, href, icon, label) => {
    const isActive = active === id;
    return `<a class="${isActive ? "active" : ""}"${isActive ? ' aria-current="page"' : ""} href="${href}"><span>${icon}</span><strong>${label}</strong></a>`;
  };
  return `<nav class="public-bottom-nav" aria-label="公共新闻导航">
    ${item("monitor", feedHref, "⌁", "监控")}
    ${item("trends", analysisHref, "↗", "趋势")}
    ${item("entities", entitiesHref, "♙", "实体")}
    ${item("targets", "#/news/feed", "◎", "目标")}
    ${item("more", analysisHref, "…", "更多")}
  </nav>`;
}

export function allowEventAdminControls({ authenticated = false, publicMode = false } = {}) {
  return Boolean(authenticated && !publicMode);
}
