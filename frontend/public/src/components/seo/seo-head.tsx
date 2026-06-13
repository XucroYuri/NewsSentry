import { useEffect } from "react"

import { applySiteSeo, clearSiteSeo, type SiteSeoPayload } from "@/lib/seo/site-seo"

export function SeoHead({ payload }: { payload: SiteSeoPayload | null }) {
  useEffect(() => {
    if (!payload) {
      clearSiteSeo()
      return
    }
    applySiteSeo(payload)
  }, [payload])

  return null
}
