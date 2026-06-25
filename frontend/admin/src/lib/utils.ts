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
