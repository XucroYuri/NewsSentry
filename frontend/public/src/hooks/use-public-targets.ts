import { useEffect, useRef, useState } from "react"

import { listTargets } from "@/lib/api"
import type { PublicTargetInfo } from "@/types/public-news"

export function usePublicTargets(
  initialTargets: PublicTargetInfo[] | null = null,
  waitForInitialData = false,
) {
  const [targets, setTargets] = useState<PublicTargetInfo[]>([])
  const initialConsumed = useRef(false)

  useEffect(() => {
    if (initialConsumed.current) return
    if (!initialTargets || initialTargets.length === 0) return
    initialConsumed.current = true
    setTargets(initialTargets)
  }, [initialTargets])

  useEffect(() => {
    if (waitForInitialData || initialConsumed.current) return
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
