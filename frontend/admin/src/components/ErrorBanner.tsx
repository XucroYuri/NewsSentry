import { AlertTriangleIcon } from "lucide-react"
import { Button } from "@/components/ui/button"

export interface ErrorBannerProps {
  error: string
  onRetry: () => void
  /** "default" = p-6, large icon (full-page error). "compact" = p-4, small icon (inline error). */
  variant?: "default" | "compact"
}

export default function ErrorBanner({ error, onRetry, variant = "default" }: ErrorBannerProps) {
  const compact = variant === "compact"
  return (
    <div
      className={`rounded-lg border border-destructive/30 bg-destructive/5 text-center ${
        compact ? "p-4" : "p-6"
      }`}
    >
      <AlertTriangleIcon
        className={`mx-auto text-destructive ${
          compact ? "mb-1 h-6 w-6" : "mb-2 h-8 w-8"
        }`}
      />
      <p className="text-sm text-destructive">{error}</p>
      <Button variant="link" onClick={onRetry} className={compact ? "mt-2" : "mt-3"}>
        重试
      </Button>
    </div>
  )
}
