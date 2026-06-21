import { useEffect, useState } from "react"

import { listTargets } from "@/lib/api"
import type { PublicTargetInfo } from "@/types/public-news"

export function usePublicTargets(
  initialTargets: PublicTargetInfo[] | null = null,
  waitForInitialData = false,
) {
  const [targets, setTargets] = useState<PublicTargetInfo[]>([])

  useEffect(() => {
    if (!initialTargets) return
    setTargets(initialTargets)
  }, [initialTargets])

  useEffect(() => {
    if (waitForInitialData) return
    let cancelled = false
    async function loadTargetList() {
      try {
        const response = await listTargets()
        if (!cancelled) setTargets(response.targets)
      } catch {
        if (!cancelled) setTargets([])
      }
    }
    void loadTargetList()
    return () => {
      cancelled = true
    }
  }, [waitForInitialData])

  return targets
}
