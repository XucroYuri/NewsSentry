import { useEffect } from "react"

import { applySiteSeo, clearSiteSeo, type SiteSeoPayload } from "@/lib/seo/site-seo"

export function SeoHead({ payload, locale = "zh" }: { payload: SiteSeoPayload | null; locale?: string }) {
  useEffect(() => {
    if (!payload) {
      clearSiteSeo(document, locale)
      return
    }
    applySiteSeo(payload)
  }, [payload, locale])

  return null
}
