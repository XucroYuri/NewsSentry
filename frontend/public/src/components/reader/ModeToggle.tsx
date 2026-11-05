import type { ReaderLocale } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"

export type ContentMode = "original" | "translated"

export function ModeToggle({ locale, mode, disabled = false, onChange }: {
  locale: ReaderLocale
  mode: ContentMode
  disabled?: boolean
  onChange: (mode: ContentMode) => void
}) {
  return (
    <div className="reader-mode" role="group" aria-label={messages[locale].mode}>
      {(["original", "translated"] as const).map((value) => (
        <button key={value} type="button" aria-pressed={mode === value} disabled={disabled} onClick={() => onChange(value)}>
          {messages[locale][value]}
        </button>
      ))}
    </div>
  )
}
