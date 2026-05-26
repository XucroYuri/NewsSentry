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
  return `#/admin/news/events/${encodeHashPart(eventId)}`;
}

export function allowEventAdminControls({ authenticated = false, publicMode = false } = {}) {
  return Boolean(authenticated && !publicMode);
}
