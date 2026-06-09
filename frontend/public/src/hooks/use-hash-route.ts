import { useCallback, useEffect, useState } from "react"

import { buildRouteHash, parseHashRoute, type PublicRoute } from "@/lib/routes"

function searchEqual(left: URLSearchParams, right: URLSearchParams) {
  return left.toString() === right.toString()
}

function routesEqual(left: PublicRoute, right: PublicRoute) {
  if (left.name !== right.name) return false
  if (left.name === "feed" && right.name === "feed") {
    return left.channel === right.channel && searchEqual(left.search, right.search)
  }
  if (left.name === "event" && right.name === "event") {
    return (
      left.eventId === right.eventId &&
      left.targetId === right.targetId &&
      searchEqual(left.search, right.search)
    )
  }
  if (left.name === "sourceDetail" && right.name === "sourceDetail") {
    return left.sourceId === right.sourceId && searchEqual(left.search, right.search)
  }
  if (left.name === "daily" && right.name === "daily") {
    return left.date === right.date && searchEqual(left.search, right.search)
  }
  if (left.name === "analysis" && right.name === "analysis") {
    return (
      left.targetId === right.targetId &&
      left.section === right.section &&
      searchEqual(left.search, right.search)
    )
  }
  return searchEqual(left.search, right.search)
}

export function useHashRoute() {
  const [route, setRoute] = useState<PublicRoute>(() => parseHashRoute(window.location.hash))

  useEffect(() => {
    const onHashChange = () =>
      setRoute((current) => {
        const next = parseHashRoute(window.location.hash)
        return routesEqual(current, next) ? current : next
      })
    window.addEventListener("hashchange", onHashChange)
    onHashChange()
    return () => window.removeEventListener("hashchange", onHashChange)
  }, [])

  const navigate = useCallback((nextRoute: PublicRoute) => {
    window.location.hash = buildRouteHash(nextRoute)
  }, [])

  return { route, navigate }
}
