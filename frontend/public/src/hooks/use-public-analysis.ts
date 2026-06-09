import { useEffect, useState } from "react"

import { getPublicTargetAnalysis, PublicNewsApiError } from "@/lib/api"
import type { PublicAnalysisResponse } from "@/types/public-news"

function normalizeError(error: unknown) {
  if (error instanceof PublicNewsApiError) return error.message
  if (error instanceof Error) return error.message
  return "态势摘要暂时不可用。"
}

export function usePublicAnalysis(targetId: string | null | undefined) {
  const [analysis, setAnalysis] = useState<PublicAnalysisResponse | null>(null)
  const [analysisError, setAnalysisError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    if (!targetId) {
      setAnalysis(null)
      setAnalysisError(null)
      return
    }
    const currentTargetId = targetId
    async function loadAnalysis() {
      try {
        const response = await getPublicTargetAnalysis(currentTargetId)
        if (!cancelled) {
          setAnalysis(response)
          setAnalysisError(null)
        }
      } catch (error) {
        if (!cancelled) {
          setAnalysis(null)
          setAnalysisError(normalizeError(error))
        }
      }
    }
    void loadAnalysis()
    return () => {
      cancelled = true
    }
  }, [targetId])

  return { analysis, analysisError }
}
