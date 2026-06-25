import { describe, expect, it } from "vitest"

import {
  cn,
  entityTypeBadge,
  formatAliases,
  getLifecycleStatus,
  NEXT_STAGE,
  roleBadgeVariant,
  roleLabel,
  scoreVariant,
  sentimentLabel,
  sentimentVariant,
  STAGE_LABELS,
  stageBadgeVariant,
} from "@/lib/utils"

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b")
  })

  it("resolves Tailwind conflicts via twMerge", () => {
    // twMerge: later classes override earlier conflicting ones
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4")
  })

  it("handles conditional classes", () => {
    expect(cn("base", false && "hidden", "extra")).toBe("base extra")
  })

  it("returns empty string for no inputs", () => {
    expect(cn()).toBe("")
  })
})

describe("scoreVariant", () => {
  it('returns "outline" for undefined', () => {
    expect(scoreVariant(undefined)).toBe("outline")
  })

  it('returns "success" for score >= 80', () => {
    expect(scoreVariant(80)).toBe("success")
    expect(scoreVariant(95)).toBe("success")
    expect(scoreVariant(100)).toBe("success")
  })

  it('returns "secondary" for 50 <= score < 80', () => {
    expect(scoreVariant(50)).toBe("secondary")
    expect(scoreVariant(65)).toBe("secondary")
    expect(scoreVariant(79)).toBe("secondary")
  })

  it('returns "outline" for score < 50', () => {
    expect(scoreVariant(0)).toBe("outline")
    expect(scoreVariant(30)).toBe("outline")
    expect(scoreVariant(49)).toBe("outline")
  })
})

describe("getLifecycleStatus", () => {
  it("extracts status from a lifecycle object", () => {
    expect(getLifecycleStatus({ status: "active" })).toBe("active")
    expect(getLifecycleStatus({ status: "idle", extra: 1 })).toBe("idle")
  })

  it("returns empty string for null or undefined", () => {
    expect(getLifecycleStatus(null)).toBe("")
    expect(getLifecycleStatus(undefined)).toBe("")
  })

  it("returns empty string for a plain string input", () => {
    expect(getLifecycleStatus("some-string")).toBe("")
  })

  it("returns empty string when lifecycle object has no status key", () => {
    expect(getLifecycleStatus({})).toBe("")
  })
})

// ──────────────────────────────────────────────────────────────
// New functions extracted from page components (M-39 extension)
// ──────────────────────────────────────────────────────────────

describe("sentimentVariant", () => {
  it('returns "secondary" for undefined or empty', () => {
    expect(sentimentVariant(undefined)).toBe("secondary")
    expect(sentimentVariant("")).toBe("secondary")
  })

  it('returns "success" for positive', () => {
    expect(sentimentVariant("positive")).toBe("success")
  })

  it('returns "destructive" for negative', () => {
    expect(sentimentVariant("negative")).toBe("destructive")
  })

  it('returns "secondary" for neutral or unknown values', () => {
    expect(sentimentVariant("neutral")).toBe("secondary")
    expect(sentimentVariant("very_negative")).toBe("secondary")
    expect(sentimentVariant("unknown")).toBe("secondary")
  })
})

describe("stageBadgeVariant", () => {
  it("maps known stages to correct variants", () => {
    expect(stageBadgeVariant("drafts")).toBe("default")
    expect(stageBadgeVariant("reviewed")).toBe("secondary")
    expect(stageBadgeVariant("published")).toBe("success")
  })

  it('returns "default" for unknown stages', () => {
    expect(stageBadgeVariant("unknown")).toBe("default")
    expect(stageBadgeVariant("")).toBe("default")
  })
})

describe("STAGE_LABELS", () => {
  it("has labels for all known stages", () => {
    expect(STAGE_LABELS.drafts).toBe("草稿")
    expect(STAGE_LABELS.reviewed).toBe("已审核")
    expect(STAGE_LABELS.published).toBe("已发布")
  })

  it("is symmetric with NEXT_STAGE keys", () => {
    const stageNames = Object.keys(STAGE_LABELS)
    const nextKeys = Object.keys(NEXT_STAGE)
    expect(stageNames.sort()).toEqual(nextKeys.sort())
  })
})

describe("NEXT_STAGE", () => {
  it("maps drafts → reviewed → published → null", () => {
    expect(NEXT_STAGE.drafts).toBe("reviewed")
    expect(NEXT_STAGE.reviewed).toBe("published")
    expect(NEXT_STAGE.published).toBeNull()
  })
})

describe("roleBadgeVariant", () => {
  it('returns "default" for admin', () => {
    expect(roleBadgeVariant("admin")).toBe("default")
  })

  it('returns "destructive" for writer', () => {
    expect(roleBadgeVariant("writer")).toBe("destructive")
  })

  it('returns "secondary" for viewer', () => {
    expect(roleBadgeVariant("viewer")).toBe("secondary")
  })

  it('returns "secondary" for unknown roles', () => {
    expect(roleBadgeVariant("")).toBe("secondary")
    expect(roleBadgeVariant("unknown")).toBe("secondary")
  })
})

describe("roleLabel", () => {
  it("translates known roles to Chinese", () => {
    expect(roleLabel("admin")).toBe("管理员")
    expect(roleLabel("writer")).toBe("编辑")
    expect(roleLabel("viewer")).toBe("只读")
  })

  it("returns unknown roles as-is", () => {
    expect(roleLabel("")).toBe("只读")
    expect(roleLabel("superadmin")).toBe("只读")
  })
})

describe("entityTypeBadge", () => {
  it("returns correct Tailwind classes for known types", () => {
    expect(entityTypeBadge("person")).toContain("bg-blue-50")
    expect(entityTypeBadge("organization")).toContain("bg-purple-50")
    expect(entityTypeBadge("location")).toContain("bg-emerald-50")
    expect(entityTypeBadge("event")).toContain("bg-amber-50")
    expect(entityTypeBadge("topic")).toContain("bg-sky-50")
  })

  it("returns muted fallback for unknown types", () => {
    expect(entityTypeBadge("unknown")).toBe("bg-muted text-muted-foreground")
    expect(entityTypeBadge("")).toBe("bg-muted text-muted-foreground")
  })
})

describe("formatAliases", () => {
  it("returns empty array for empty string", () => {
    expect(formatAliases("")).toEqual([])
  })

  it("parses JSON array", () => {
    expect(formatAliases('["meloni", "giorgia"]')).toEqual(["meloni", "giorgia"])
    expect(formatAliases('["single"]')).toEqual(["single"])
  })

  it("wraps non-array JSON as single-element array", () => {
    // String(new Object(...)) produces "[object Object]", matching runtime behavior
    expect(formatAliases('{"name": "test"}')).toEqual(["[object Object]"])
  })

  it("falls back to comma-split on non-JSON", () => {
    expect(formatAliases("meloni, giorgia, salvini")).toEqual(["meloni", "giorgia", "salvini"])
  })

  it("trims and filters empty entries in fallback", () => {
    expect(formatAliases("a, , b ,")).toEqual(["a", "b"])
  })

  it("handles empty JSON array", () => {
    expect(formatAliases("[]")).toEqual([])
  })
})

describe("sentimentLabel", () => {
  it("translates known sentiments to Chinese", () => {
    expect(sentimentLabel("positive")).toBe("正面")
    expect(sentimentLabel("negative")).toBe("负面")
    expect(sentimentLabel("neutral")).toBe("中性")
    expect(sentimentLabel("very_negative")).toBe("极负面")
  })

  it("returns unknown values as-is", () => {
    expect(sentimentLabel("mixed")).toBe("mixed")
    expect(sentimentLabel("")).toBe("")
  })
})
