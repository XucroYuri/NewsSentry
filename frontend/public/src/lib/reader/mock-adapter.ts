import { asReaderLocale, type ReaderLocale } from "./locales"
import { ReaderApiError, type ReaderAdapter, type ReaderArticle } from "./types"

export const mockImageUrl = `/api/v1/reader/image?u=${encodeURIComponent("https://example.com/harbour.png")}&s=${"0".repeat(64)}`

// 明确标记的虚构样稿，供本机 UI 验收；不向外站或模型发请求。
const copy: Record<ReaderLocale, [string, string, string, string]> = {
  zh: ["关键海峡通航窗口收紧：能源绕行与外交磋商并行", "背景：航运走廊承压", "本地演示样稿。港口观察员记录了本周商船通航窗口的变化。航运公司正在评估绕行路线、保险费用与到港时间，并提醒客户预留额外的运输时间。相关信息仍需与港口公告及原始记录逐一核对。", "持续观察：信息与不确定性"],
  en: ["Narrower shipping windows put energy routes and diplomacy in focus", "Background: pressure on the shipping corridor", "This is a fictional local demonstration. Port observers have recorded changes to merchant shipping windows this week. Operators are reviewing alternative routes, insurance costs and arrival times, while advising customers to allow additional transit time. These observations still need to be checked against port notices and original records.", "What to watch: information and uncertainty"],
  es: ["Menos ventanas de navegación: rutas energéticas y diálogo diplomático", "Contexto: presión sobre el corredor marítimo", "Este es un ejemplo ficticio para una demostración local. Los observadores portuarios han registrado cambios en las ventanas de navegación esta semana.", "Seguimiento: información e incertidumbre"],
  ar: ["تضييق نوافذ الملاحة: مسارات الطاقة والمشاورات الدبلوماسية", "الخلفية: ضغوط على الممر الملاحي", "هذا نص خيالي للعرض المحلي. سجّل مراقبو الموانئ تغيرات في فترات مرور السفن التجارية هذا الأسبوع. تراجع شركات الشحن المسارات البديلة وتكاليف التأمين ومواعيد الوصول، وتنصح العملاء بإتاحة وقت إضافي للنقل. لا تزال هذه المعلومات بحاجة إلى التحقق من إعلانات الموانئ والسجلات الأصلية.", "متابعة: المعلومات وعدم اليقين"],
  fr: ["Navigation restreinte : routes énergétiques et dialogue diplomatique", "Contexte : pression sur le corridor maritime", "Ceci est un exemple fictif pour une démonstration locale. Les observateurs portuaires ont relevé des changements dans les créneaux de navigation cette semaine.", "À suivre : information et incertitude"],
  ja: ["海峡の通航時間が短縮：エネルギー輸送と外交協議の動向", "背景：航路への圧力", "これはローカルデモ用の架空の記事です。港湾の観測担当者は今週、商船の通航可能時間の変化を記録しました。", "今後の注目点：情報と不確実性"],
  de: ["Kürzere Schifffahrtsfenster: Energierouten und diplomatische Gespräche", "Hintergrund: Druck auf den Schifffahrtskorridor", "Dies ist ein fiktiver Text für eine lokale Demo. Hafenbeobachter haben diese Woche Änderungen der Durchfahrtszeiten dokumentiert.", "Ausblick: Informationen und Unsicherheit"],
  it: ["Finestre di navigazione ridotte: rotte energetiche e dialogo diplomatico", "Contesto: pressione sul corridoio marittimo", "Questo è un testo fittizio per una dimostrazione locale. Gli osservatori portuali hanno registrato cambiamenti nelle finestre di navigazione questa settimana.", "Da seguire: informazioni e incertezza"],
  pt: ["Janelas de navegação reduzidas: rotas energéticas e diálogo diplomático", "Contexto: pressão sobre o corredor marítimo", "Este é um texto fictício para uma demonstração local. Os observadores portuários registaram alterações nas janelas de navegação esta semana.", "A acompanhar: informação e incerteza"],
  ko: ["해협 통항 시간 축소: 에너지 운송과 외교 협의의 흐름", "배경: 해상 운송로의 압박", "이 글은 로컬 데모를 위한 가상 기사입니다. 항만 관측 담당자들은 이번 주 상선 통항 시간의 변화를 기록했습니다.", "주목할 점: 정보와 불확실성"],
}

function markdown(locale: ReaderLocale) {
  const [title, heading, paragraph, followup] = copy[locale]
  return `# ${title}\n\n## ${heading}\n\n${paragraph}\n\n![${heading}](${mockImageUrl})\n\n## ${followup}\n\n${Array.from({ length: 6 }, () => paragraph).join("\n\n")}\n\n### ${heading}\n\n${paragraph}\n\n> ${paragraph}`
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException("Aborted", "AbortError"))
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort)
      resolve()
    }, ms)
    if (signal?.aborted) abort()
    else signal?.addEventListener("abort", abort, { once: true })
  })
}

export const mockArticle: ReaderArticle = {
  title: copy.en[0],
  markdown: markdown("en"),
  lang: "en",
  sourceUrl: "https://example.com/news/shipping-corridor",
  contentHash: "0123456789abcdef0123456789abcdef",
  attribution: "News Sentry · Local demonstration / 本地虚构样稿",
  images: [{ src: "https://example.com/harbour.png", proxyUrl: mockImageUrl, alt: copy.en[1] }],
}

export function createMockReaderAdapter(state = ""): ReaderAdapter {
  return {
    async preview(_input, signal) {
      await pause(40, signal)
      if (state === "preview-unavailable") throw new ReaderApiError(422, "EXTRACTION_FAILED", "Local fixture")
      if (state !== "image-fail") return mockArticle
      const failed = mockImageUrl.replace("harbour.png", "missing.png")
      return { ...mockArticle, markdown: mockArticle.markdown.split(mockImageUrl).join(failed), images: mockArticle.images.map((image) => ({ ...image, proxyUrl: failed })) }
    },
    async translate(input, signal) {
      await pause(state === "translate-loading" ? 30_000 : 160, signal)
      if (state === "translate-unavailable") throw new ReaderApiError(503, "TRANSLATION_UNAVAILABLE", "Local fixture")
      const locale = asReaderLocale(input.targetLang) ?? "zh"
      let translated = markdown(locale)
      if (state === "image-fail") translated = translated.split(mockImageUrl).join(mockImageUrl.replace("harbour.png", "missing.png"))
      return { translated, lang: locale, cached: false, provider: "local-fixture" }
    },
  }
}
