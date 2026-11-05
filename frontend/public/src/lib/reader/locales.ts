export const readerLocales = ["zh", "en", "es", "ar", "fr", "ja", "de", "it", "pt", "ko"] as const
export type ReaderLocale = (typeof readerLocales)[number]

export const localeInfo: Record<ReaderLocale, { name: string; flag: string }> = {
  zh: { name: "中文", flag: "cn" },
  en: { name: "English", flag: "gb" },
  es: { name: "Español", flag: "es" },
  ar: { name: "العربية", flag: "sa" },
  fr: { name: "Français", flag: "fr" },
  ja: { name: "日本語", flag: "jp" },
  de: { name: "Deutsch", flag: "de" },
  it: { name: "Italiano", flag: "it" },
  pt: { name: "Português", flag: "pt" },
  ko: { name: "한국어", flag: "kr" },
}

export function asReaderLocale(value?: string | null): ReaderLocale | undefined {
  const locale = value?.toLowerCase().split("-")[0]
  return readerLocales.find((candidate) => candidate === locale)
}

export function preferredLocale(explicit?: string | null): ReaderLocale {
  const locale = asReaderLocale(explicit)
  if (locale) return locale
  try {
    const saved = asReaderLocale(localStorage.getItem("news-sentry-reader-locale"))
    if (saved) return saved
  } catch {
    // 禁用存储时仍按浏览器语言选择。
  }
  const languages = typeof navigator === "undefined" ? [] : [...(navigator.languages ?? []), navigator.language]
  return languages.map(asReaderLocale).find((candidate) => candidate !== undefined) ?? "en"
}

export function saveLocale(locale: ReaderLocale) {
  try {
    localStorage.setItem("news-sentry-reader-locale", locale)
  } catch {
    // 禁用存储时 URL 仍保留本次选择。
  }
}
