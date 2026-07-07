import "@testing-library/jest-dom/vitest"

import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { NewsList, NewsListRow, SortTabs, type SortMode } from "@/components/news-list-row"
import type { PublicNewsItem } from "@/types/public-news"

afterEach(cleanup)

// Stub history.pushState + popstate so NewsListRow navigation doesn't blow up jsdom.
const originalPushState = window.history.pushState
const originalDispatchEvent = window.dispatchEvent
beforeEach(() => {
  window.history.pushState = vi.fn()
  window.dispatchEvent = vi.fn()
})
afterEach(() => {
  window.history.pushState = originalPushState
  window.dispatchEvent = originalDispatchEvent
})

function makeItem(overrides: Partial<PublicNewsItem> = {}): PublicNewsItem {
  return {
    id: "evt-1",
    targetId: "italy",
    targetLabel: "Italy",
    source: { id: "ansa", name: "ANSA", type: "rss" },
    publishedAt: "2026-07-07T10:00:00Z",
    title: "默认新闻标题",
    detailUrl: "/public-app/events/evt-1",
    tags: [],
    issueTags: [],
    relatedTags: [],
    regionTags: [],
    entities: [],
    relatedCount: 0,
    valueLabel: "精选",
    valueScore: 80,
    chinaRelevanceLabel: "中",
    hnScore: 5.47,
    points: 8.0,
    gravityAgeHours: 2.0,
    voteCount: 0,
    ...overrides,
  }
}

describe("NewsListRow", () => {
  it("renders rank, title, source, and recommendation score metadata", () => {
    render(<NewsListRow item={makeItem()} rank={1} />)
    expect(screen.getByText("1")).toBeInTheDocument()
    expect(screen.getByText("默认新闻标题")).toBeInTheDocument()
    expect(screen.getByText(/ANSA/)).toBeInTheDocument()
    // Recommendation score is shown without exposing internal formula terms.
    expect(screen.getByText("推荐")).toBeInTheDocument()
    expect(screen.getByText(/5\.47/)).toBeInTheDocument()
  })

  it("marks top-3 ranks with hot styling (golden accent)", () => {
    const { container } = render(<NewsListRow item={makeItem()} rank={1} />)
    const article = container.querySelector("article")
    expect(article?.className).toContain("border-l-amber")
  })

  it("does not mark rank > 3 as hot by default", () => {
    const { container } = render(<NewsListRow item={makeItem()} rank={5} />)
    const article = container.querySelector("article")
    expect(article?.className).toContain("border-l-transparent")
  })

  it("forces hot styling when hot prop is set", () => {
    const { container } = render(<NewsListRow item={makeItem()} rank={10} hot />)
    const article = container.querySelector("article")
    expect(article?.className).toContain("border-l-amber")
  })

  it("renders domain in parens when originalUrl is present", () => {
    render(
      <NewsListRow
        item={makeItem({ originalUrl: "https://www.example.com/article/123" })}
        rank={1}
      />,
    )
    expect(screen.getByText(/\(example\.com\)/)).toBeInTheDocument()
  })

  it("falls back to source name when originalUrl is missing", () => {
    render(<NewsListRow item={makeItem({ originalUrl: null })} rank={1} />)
    expect(screen.getByText(/\(ANSA\)/)).toBeInTheDocument()
  })

  it("handles missing HN fields gracefully (defensive fallback)", () => {
    // Simulate old/cached API payload missing hnScore/points/gravityAgeHours.
    const stale = makeItem()
    // Strip HN fields to simulate undefined (TS allows this via cast).
    const partial = { ...stale, hnScore: undefined, points: undefined, gravityAgeHours: undefined } as unknown as PublicNewsItem
    expect(() => render(<NewsListRow item={partial} rank={1} />)).not.toThrow()
  })

  it("renders related count when > 0", () => {
    render(<NewsListRow item={makeItem({ relatedCount: 3 })} rank={1} />)
    expect(screen.getByText(/相关 3/)).toBeInTheDocument()
  })

  it("omits related count when 0", () => {
    render(<NewsListRow item={makeItem({ relatedCount: 0 })} rank={1} />)
    expect(screen.queryByText(/相关/)).not.toBeInTheDocument()
  })

  it("renders age label instead of raw timestamp", () => {
    // publishedAt is recent → should show "刚刚" or "分钟前"
    const recent = new Date(Date.now() - 5 * 60_000).toISOString()
    render(<NewsListRow item={makeItem({ publishedAt: recent })} rank={1} />)
    expect(screen.getByText(/分钟前|刚刚/)).toBeInTheDocument()
  })

  it("applies read opacity when isRead is true", () => {
    const { container } = render(<NewsListRow item={makeItem()} rank={1} isRead />)
    const article = container.querySelector("article")
    expect(article?.className).toContain("opacity-70")
  })

  it("applies entering animation when isNew is true", () => {
    const { container } = render(<NewsListRow item={makeItem()} rank={1} isNew />)
    const article = container.querySelector("article")
    expect(article?.className).toContain("news-card-entering")
  })
})

describe("NewsList", () => {
  const items: PublicNewsItem[] = [
    makeItem({ id: "a", hnScore: 1.0, title: "Item A", publishedAt: "2026-07-07T08:00:00Z" }),
    makeItem({ id: "b", hnScore: 5.0, title: "Item B", publishedAt: "2026-07-07T09:00:00Z" }),
    makeItem({ id: "c", hnScore: 3.0, title: "Item C", publishedAt: "2026-07-07T10:00:00Z" }),
  ]

  it("sorts by hnScore descending when sortMode=top", () => {
    render(<NewsList items={items} sortMode="top" />)
    const rows = screen.getAllByRole("listitem")
    expect(rows[0]).toHaveTextContent("Item B")
    expect(rows[1]).toHaveTextContent("Item C")
    expect(rows[2]).toHaveTextContent("Item A")
  })

  it("sorts by publishedAt descending when sortMode=recent", () => {
    render(<NewsList items={items} sortMode="recent" />)
    const rows = screen.getAllByRole("listitem")
    expect(rows[0]).toHaveTextContent("Item C")
    expect(rows[1]).toHaveTextContent("Item B")
    expect(rows[2]).toHaveTextContent("Item A")
  })

  it("sorts by breakingScore/valueScore descending when sortMode=breaking", () => {
    const breakingItems: PublicNewsItem[] = [
      makeItem({ id: "a", breakingScore: 30, title: "Brk A", publishedAt: "2026-07-07T08:00:00Z" }),
      makeItem({ id: "b", breakingScore: 90, title: "Brk B", publishedAt: "2026-07-07T09:00:00Z" }),
      makeItem({ id: "c", breakingScore: 60, title: "Brk C", publishedAt: "2026-07-07T10:00:00Z" }),
    ]
    render(<NewsList items={breakingItems} sortMode="breaking" />)
    const rows = screen.getAllByRole("listitem")
    expect(rows[0]).toHaveTextContent("Brk B")
    expect(rows[1]).toHaveTextContent("Brk C")
    expect(rows[2]).toHaveTextContent("Brk A")
  })

  it("preserves insertion order on ties in top mode (stable sort)", () => {
    const tiedItems: PublicNewsItem[] = [
      makeItem({ id: "first", hnScore: 5.0, title: "First", publishedAt: "2026-07-07T08:00:00Z" }),
      makeItem({ id: "second", hnScore: 5.0, title: "Second", publishedAt: "2026-07-07T09:00:00Z" }),
      makeItem({ id: "third", hnScore: 5.0, title: "Third", publishedAt: "2026-07-07T10:00:00Z" }),
    ]
    render(<NewsList items={tiedItems} sortMode="top" />)
    const rows = screen.getAllByRole("listitem")
    expect(rows[0]).toHaveTextContent("First")
    expect(rows[1]).toHaveTextContent("Second")
    expect(rows[2]).toHaveTextContent("Third")
  })

  it("renders empty state message when items is empty", () => {
    render(<NewsList items={[]} sortMode="top" />)
    expect(screen.getByText("当前没有匹配的新闻条目。")).toBeInTheDocument()
  })

  it("renders rank numbers starting from 1", () => {
    render(<NewsList items={items} sortMode="top" />)
    expect(screen.getByText("1")).toBeInTheDocument()
    expect(screen.getByText("2")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
  })

  it("does not mutate input items array", () => {
    const original = [...items]
    render(<NewsList items={items} sortMode="top" />)
    expect(items.map((i) => i.id)).toEqual(original.map((i) => i.id))
  })

  it("renders as ordered list with accessible label", () => {
    render(<NewsList items={items} sortMode="top" />)
    expect(screen.getByRole("list", { name: "新闻排名列表" })).toBeInTheDocument()
  })

  it("marks read items via readIds set", () => {
    const { container } = render(
      <NewsList
        items={[makeItem({ id: "read-one" })]}
        sortMode="top"
        readIds={new Set(["read-one"])}
      />,
    )
    // <article> has role="link" override; query DOM directly.
    const article = container.querySelector("article")
    expect(article?.className).toContain("opacity-70")
  })

  it("marks new items via recentlyInsertedIds set", () => {
    const { container } = render(
      <NewsList
        items={[makeItem({ id: "fresh-one" })]}
        sortMode="top"
        recentlyInsertedIds={new Set(["fresh-one"])}
      />,
    )
    const article = container.querySelector("article")
    expect(article?.className).toContain("news-card-entering")
  })
})

describe("SortTabs", () => {
  it("renders three tabs: 推荐, 最新, 突发", () => {
    render(<SortTabs value="top" onChange={() => {}} />)
    expect(screen.getByText("推荐")).toBeInTheDocument()
    expect(screen.getByText("最新")).toBeInTheDocument()
    expect(screen.getByText("突发")).toBeInTheDocument()
  })

  it("marks active tab with aria-pressed=true", () => {
    render(<SortTabs value="recent" onChange={() => {}} />)
    expect(screen.getByRole("button", { name: /^最新/ })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("button", { name: /^推荐/ })).toHaveAttribute("aria-pressed", "false")
    expect(screen.getByRole("button", { name: /^突发/ })).toHaveAttribute("aria-pressed", "false")
  })

  it("applies golden accent class to active tab", () => {
    render(<SortTabs value="top" onChange={() => {}} />)
    const topBtn = screen.getByRole("button", { name: /^推荐/ })
    expect(topBtn.className).toContain("text-amber")
  })

  it("calls onChange with selected mode when tab clicked", () => {
    const onChange = vi.fn()
    render(<SortTabs value="top" onChange={onChange} />)
    fireEvent.click(screen.getByRole("button", { name: /^最新/ }))
    expect(onChange).toHaveBeenCalledWith("recent")
  })

  it("renders count badges when counts prop is provided", () => {
    render(
      <SortTabs
        value="top"
        onChange={() => {}}
        counts={{ top: 10, recent: 15, breaking: 3 }}
      />,
    )
    // Counts appear as small tabular numbers next to labels.
    expect(screen.getByText("10")).toBeInTheDocument()
    expect(screen.getByText("15")).toBeInTheDocument()
    expect(screen.getByText("3")).toBeInTheDocument()
  })

  it("omits count badges when counts prop is absent", () => {
    render(<SortTabs value="top" onChange={() => {}} />)
    // Only 3 tab labels, no extra count numbers.
    const buttons = screen.getAllByRole("button")
    expect(buttons).toHaveLength(3)
  })

  it("supports all three sort modes as value prop", () => {
    const modes: SortMode[] = ["top", "recent", "breaking"]
    const labels = ["推荐", "最新", "突发"] as const
    modes.forEach((mode, idx) => {
      const { unmount } = render(<SortTabs value={mode} onChange={() => {}} />)
      const activeTab = screen.getByRole("button", { name: new RegExp(`^${labels[idx]}`) })
      expect(activeTab).toHaveAttribute("aria-pressed", "true")
      unmount()
    })
  })
})
