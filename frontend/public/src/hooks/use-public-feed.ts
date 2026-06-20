import { useCallback, useEffect, useState } from "react"

import { listPublicNews, PublicNewsApiError } from "@/lib/api"
import {
  appendOlderItems,
  type FeedFilters,
  makeFeedQuery,
  mergeNewerItems,
  nextPollDelayMs,
  shouldPausePolling,
} from "@/lib/feed-state"
import type { PublicNewsItem } from "@/types/public-news"

export type FeedStatus = "loading" | "ready" | "empty" | "error"

export interface FeedState {
  status: FeedStatus
  items: PublicNewsItem[]
  pendingNewItems: PublicNewsItem[]
  recentlyInsertedIds: string[]
  latestCursor: string | null
  nextCursor: string | null
  etag: string | null
  pollAfterMs: number | null
  total: number
  error?: string
}

const initialFeedState: FeedState = {
  status: "loading",
  items: [],
  pendingNewItems: [],
  recentlyInsertedIds: [],
  latestCursor: null,
  nextCursor: null,
  etag: null,
  pollAfterMs: 30_000,
  total: 0,
}

function normalizeError(error: unknown) {
  if (error instanceof PublicNewsApiError) return error.message
  if (error instanceof Error) return error.message
  return "公共新闻接口暂时不可用，请稍后重试。"
}

function shouldFallbackFeatured(filters: FeedFilters) {
  return (
    filters.channel === "featured" &&
    !filters.targetId &&
    !filters.sourceId &&
    !filters.category &&
    !filters.search &&
    !filters.date
  )
}

function sortByValue(items: PublicNewsItem[]) {
  return [...items].sort((left, right) => (right.valueScore ?? 0) - (left.valueScore ?? 0))
}

export function usePublicFeed(filters: FeedFilters, options: { poll?: boolean } = {}) {
  const [feedState, setFeedState] = useState<FeedState>(initialFeedState)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [pollFailures, setPollFailures] = useState(0)
  const [pollNonce, setPollNonce] = useState(0)
  const poll = options.poll ?? true

  const loadFeed = useCallback(
    async (mode: "replace" | "refresh" = "replace") => {
      setRefreshing(true)
      setPollFailures(0)
      setFeedState((current) => ({
        ...current,
        status: current.items.length > 0 && mode === "refresh" ? "ready" : "loading",
        error: undefined,
        pendingNewItems: mode === "replace" ? [] : current.pendingNewItems,
        recentlyInsertedIds: mode === "replace" ? [] : current.recentlyInsertedIds,
      }))
      try {
        let result = await listPublicNews(makeFeedQuery(filters))
        let items = result.data?.items ?? []
        if (items.length === 0 && shouldFallbackFeatured(filters)) {
          const fallback = await listPublicNews({ pageSize: filters.pageSize })
          const fallbackItems = fallback.data?.items ?? []
          if (fallbackItems.length > 0) {
            result = fallback
            items = sortByValue(fallbackItems)
          }
        }
        setFeedState({
          status: items.length > 0 ? "ready" : "empty",
          items,
          pendingNewItems: [],
          recentlyInsertedIds: [],
          latestCursor: result.data?.latestCursor ?? null,
          nextCursor: result.data?.nextCursor ?? null,
          etag: result.etag,
          pollAfterMs: result.pollAfterMs ?? result.data?.pollAfterMs ?? 30_000,
          total: result.data?.total ?? items.length,
        })
      } catch (error) {
        setFeedState((current) => ({
          ...current,
          status: "error",
          error: normalizeError(error),
        }))
      } finally {
        setRefreshing(false)
      }
    },
    [filters],
  )

  useEffect(() => {
    void loadFeed("replace")
  }, [loadFeed])

  useEffect(() => {
    if (!poll || !feedState.latestCursor || feedState.status === "loading") return
    const delay = nextPollDelayMs({
      serverMs: feedState.pollAfterMs,
      failureCount: pollFailures,
    })
    const timeoutId = window.setTimeout(() => {
      if (
        shouldPausePolling({
          visibilityState: document.visibilityState,
          online: navigator.onLine,
        })
      ) {
        setPollNonce((current) => current + 1)
        return
      }

      async function pollNewer() {
        try {
          const result = await listPublicNews(
            {
              ...makeFeedQuery(filters),
              sinceCursor: feedState.latestCursor ?? undefined,
              pageSize: filters.pageSize,
            },
            { etag: feedState.etag ?? undefined },
          )
          setPollFailures(0)
          if (result.notModified || !result.data) {
            setFeedState((current) => ({
              ...current,
              etag: result.etag ?? current.etag,
              pollAfterMs: result.pollAfterMs ?? current.pollAfterMs,
            }))
            return
          }
          setFeedState((current) => {
            const incomingItems = result.data?.items ?? []
            const existingIds = new Set(current.items.map((item) => item.id))
            const newItems = incomingItems.filter((item) => !existingIds.has(item.id))
            return {
              ...current,
              items: newItems.length > 0 ? mergeNewerItems(current.items, newItems) : current.items,
              pendingNewItems: [],
              recentlyInsertedIds: newItems.map((item) => item.id),
              status: current.items.length > 0 || newItems.length > 0 ? "ready" : current.status,
              latestCursor: result.data?.latestCursor ?? current.latestCursor,
              etag: result.etag,
              pollAfterMs: result.pollAfterMs ?? result.data?.pollAfterMs ?? current.pollAfterMs,
              total: result.data?.total ?? current.total,
            }
          })
        } catch {
          setPollFailures((current) => current + 1)
        } finally {
          setPollNonce((current) => current + 1)
        }
      }

      void pollNewer()
    }, delay)
    return () => window.clearTimeout(timeoutId)
  }, [
    feedState.etag,
    feedState.latestCursor,
    feedState.pollAfterMs,
    feedState.status,
    filters,
    poll,
    pollFailures,
    pollNonce,
  ])

  const loadMore = useCallback(async () => {
    if (!feedState.nextCursor || loadingMore) return
    setLoadingMore(true)
    try {
      const result = await listPublicNews({
        ...makeFeedQuery(filters),
        beforeCursor: feedState.nextCursor,
        pageSize: filters.pageSize,
      })
      const olderItems = result.data?.items ?? []
      setFeedState((current) => ({
        ...current,
        status: current.items.length > 0 || olderItems.length > 0 ? "ready" : "empty",
        items: appendOlderItems(current.items, olderItems),
        recentlyInsertedIds: [],
        nextCursor: result.data?.nextCursor ?? null,
        latestCursor: result.data?.latestCursor ?? current.latestCursor,
        etag: result.etag ?? current.etag,
        pollAfterMs: result.pollAfterMs ?? current.pollAfterMs,
        total: result.data?.total ?? current.total,
      }))
    } catch (error) {
      setFeedState((current) => ({
        ...current,
        status: current.items.length > 0 ? "ready" : "error",
        error: normalizeError(error),
      }))
    } finally {
      setLoadingMore(false)
    }
  }, [feedState.nextCursor, filters, loadingMore])

  const applyPending = useCallback(() => {
    setFeedState((current) => ({
      ...current,
      items: mergeNewerItems(current.items, current.pendingNewItems),
      pendingNewItems: [],
      recentlyInsertedIds: current.pendingNewItems.map((item) => item.id),
      status: "ready",
    }))
  }, [])

  return {
    feedState,
    refreshing,
    loadingMore,
    loadFeed,
    loadMore,
    applyPending,
  }
}
