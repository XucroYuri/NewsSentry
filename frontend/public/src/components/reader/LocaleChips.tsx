import { localeInfo, readerLocales, type ReaderLocale } from "@/lib/reader/locales"
import messages from "@/lib/reader/messages.json"

export function LocaleChips({ locale, disabled = false, onChange }: {
  locale: ReaderLocale
  disabled?: boolean
  onChange: (locale: ReaderLocale) => void
}) {
  return (
    <div className="reader-locales" role="group" aria-label={messages[locale].languages}>
      {readerLocales.map((language) => (
        <button
          type="button"
          key={language}
          className="reader-locale"
          lang={language}
          dir="ltr"
          title={localeInfo[language].name}
          aria-label={`${language.toUpperCase()} · ${localeInfo[language].name}`}
          aria-pressed={locale === language}
          disabled={disabled}
          onClick={() => onChange(language)}
        >
          <img src={`${import.meta.env.BASE_URL}flags/${localeInfo[language].flag}.svg`} alt="" width="20" height="15" loading="lazy" decoding="async" />
          <span>{language.toUpperCase()}</span>
        </button>
      ))}
    </div>
  )
}
