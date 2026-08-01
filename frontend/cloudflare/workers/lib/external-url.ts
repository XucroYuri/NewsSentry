const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
const MAX_EXTERNAL_URL_LENGTH = 4096;

export type ExternalUrlResult =
  | { ok: true; normalizedUrl: string }
  | { ok: false; reason: "missing_url" | "unsafe_url" };

/**
 * Normalize an untrusted external URL without silently repairing ambiguous input.
 * Network-layer SSRF checks still run at fetch time; this function protects the
 * ingest and rendering boundary.
 */
export function validateExternalUrl(value: unknown): ExternalUrlResult {
  if (typeof value !== "string" || value.length === 0) {
    return { ok: false, reason: "missing_url" };
  }
  if (
    value !== value.trim() ||
    value.length > MAX_EXTERNAL_URL_LENGTH ||
    CONTROL_CHARACTERS.test(value) ||
    value.includes("\\")
  ) {
    return { ok: false, reason: "unsafe_url" };
  }

  try {
    const parsed = new URL(value);
    if (
      (parsed.protocol !== "https:" && parsed.protocol !== "http:") ||
      !parsed.hostname ||
      parsed.username ||
      parsed.password
    ) {
      return { ok: false, reason: "unsafe_url" };
    }
    return { ok: true, normalizedUrl: parsed.href };
  } catch {
    return { ok: false, reason: "unsafe_url" };
  }
}

/** Drop unsafe entries instead of passing untrusted URL schemes to renderers. */
export function sanitizeExternalUrlList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((candidate) => {
    const result = validateExternalUrl(candidate);
    return result.ok ? [result.normalizedUrl] : [];
  });
}
