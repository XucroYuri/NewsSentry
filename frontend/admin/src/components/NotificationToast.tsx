/**
 * NotificationToast — 管理后台实时通知的 Toast 组件。
 *
 * 右下角固定浮动显示，5s 自动消失，点击可关闭。
 * 支持按 sentiment 显示不同图标颜色。
 */

import { useState } from "react"
import { AlertCircleIcon, CheckCircle2Icon, XIcon } from "lucide-react"

import type { AlertPayload } from "@/hooks/useNotificationWebSocket"

interface NotificationToastProps {
  alerts: AlertPayload[]
  onDismiss: (eventId: string) => void
}

const SENTIMENT_ICONS: Record<string, { icon: typeof AlertCircleIcon; color: string }> = {
  positive: { icon: CheckCircle2Icon, color: "text-green-500" },
  negative: { icon: AlertCircleIcon, color: "text-red-500" },
  very_negative: { icon: AlertCircleIcon, color: "text-red-600" },
}

function getSentimentConfig(sentiment: string) {
  return SENTIMENT_ICONS[sentiment.toLowerCase()] ?? {
    icon: AlertCircleIcon,
    color: "text-blue-500",
  }
}

export default function NotificationToast({ alerts, onDismiss }: NotificationToastProps) {
  // Track dismissed alerts locally for animation
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())

  if (alerts.length === 0) return null

  // Show only the latest 3 alerts
  const visible = alerts.slice(0, 3).filter((a) => !dismissed.has(a.event_id))

  function handleDismiss(eventId: string) {
    setDismissed((prev) => new Set(prev).add(eventId))
    // Allow parent to clean up after animation
    setTimeout(() => {
      onDismiss(eventId)
      setDismissed((prev) => {
        const next = new Set(prev)
        next.delete(eventId)
        return next
      })
    }, 300)
  }

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
      {visible.map((alert) => {
        const cfg = getSentimentConfig(alert.sentiment)
        const Icon = cfg.icon
        return (
          <div
            key={alert.event_id}
            className="flex items-start gap-3 rounded-lg border border-border bg-card px-4 py-3 shadow-lg animate-in slide-in-from-right-2"
          >
            <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${cfg.color}`} />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">
                {alert.title}
              </p>
              <p className="text-xs text-muted-foreground mt-0.5">
                价值分: {alert.news_value_score}
                {alert.entity_names.length > 0 &&
                  ` · ${alert.entity_names.slice(0, 2).join(", ")}`}
              </p>
            </div>
            <button
              onClick={() => handleDismiss(alert.event_id)}
              className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              aria-label="关闭通知"
            >
              <XIcon className="h-4 w-4" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
