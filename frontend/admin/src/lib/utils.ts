import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** 0-100 新闻分值 → Badge variant。 */
export function scoreVariant(
  score: number | undefined,
): "success" | "destructive" | "secondary" | "outline" {
  if (score === undefined) return "outline"
  if (score >= 80) return "success"
  if (score >= 50) return "secondary"
  return "outline"
}

/** 提取 target lifecycle 状态字符串（admin target info 使用）。 */
export function getLifecycleStatus(
  lifecycle: Record<string, unknown> | string | null | undefined,
): string {
  if (typeof lifecycle === "object" && lifecycle !== null) {
    return String(lifecycle.status ?? "")
  }
  return ""
}

// ── 以下函数从各页面组件中提取，便于测试和复用 ──

/** 情感 → Badge variant。 */
export function sentimentVariant(
  sentiment: string | undefined,
): "success" | "destructive" | "secondary" {
  if (!sentiment) return "secondary"
  if (sentiment === "positive") return "success"
  if (sentiment === "negative") return "destructive"
  return "secondary"
}

/** 草稿审核阶段 → Badge variant。 */
export function stageBadgeVariant(
  stage: string,
): "default" | "secondary" | "success" {
  const map: Record<string, "default" | "secondary" | "success"> = {
    drafts: "default",
    reviewed: "secondary",
    published: "success",
  }
  return map[stage] ?? "default"
}

/** 草稿审核阶段标签映射。 */
export const STAGE_LABELS: Record<string, string> = {
  drafts: "草稿",
  reviewed: "已审核",
  published: "已发布",
}

/** 草稿审核阶段流转映射。 */
export const NEXT_STAGE: Record<string, string | null> = {
  drafts: "reviewed",
  reviewed: "published",
  published: null,
}

/** 用户角色 → Badge variant。 */
export function roleBadgeVariant(
  role: string,
): "default" | "secondary" | "destructive" {
  if (role === "admin") return "default"
  if (role === "writer") return "destructive"
  return "secondary"
}

/** 用户角色 → 中文标签。 */
export function roleLabel(role: string): string {
  if (role === "admin") return "管理员"
  if (role === "writer") return "编辑"
  return "只读"
}

/** 实体类型 → Tailwind CSS 类名。 */
export function entityTypeBadge(type: string): string {
  const colors: Record<string, string> = {
    person: "bg-blue-50 text-blue-700 border-blue-200",
    organization: "bg-purple-50 text-purple-700 border-purple-200",
    location: "bg-emerald-50 text-emerald-700 border-emerald-200",
    event: "bg-amber-50 text-amber-700 border-amber-200",
    topic: "bg-sky-50 text-sky-700 border-sky-200",
  }
  return colors[type] ?? "bg-muted text-muted-foreground"
}

/** 解析别名（JSON 数组或逗号分隔字符串）→ string[]。 */
export function formatAliases(aliases: string): string[] {
  if (!aliases) return []
  try {
    const parsed = JSON.parse(aliases)
    return Array.isArray(parsed) ? parsed : [String(parsed)]
  } catch {
    return aliases.split(",").map((s) => s.trim()).filter(Boolean)
  }
}

/** 情感英文值 → 中文标签。 */
export function sentimentLabel(s: string): string {
  const map: Record<string, string> = {
    positive: "正面",
    negative: "负面",
    neutral: "中性",
    very_negative: "极负面",
  }
  return map[s] ?? s
}
