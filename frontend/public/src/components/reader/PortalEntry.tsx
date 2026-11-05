import { lazy, Suspense, useEffect, useState } from "react"

import { parseReaderRoute, readerMode } from "@/lib/reader/routes"

const PublicApp = lazy(() => import("@/App"))
const ReaderPage = lazy(() => import("./ReaderPage"))

export default function PortalEntry() {
  const [route, setRoute] = useState(() => parseReaderRoute(window.location))
  useEffect(() => {
    const sync = () => setRoute(parseReaderRoute(window.location))
    window.addEventListener("popstate", sync)
    return () => window.removeEventListener("popstate", sync)
  }, [])
  return (
    <Suspense fallback={<main className="p-4" role="status" aria-label="News Sentry">News Sentry</main>}>
      {route ? <ReaderPage route={route} mode={readerMode()} /> : <PublicApp />}
    </Suspense>
  )
}
