import { ChevronLeftIcon, ChevronRightIcon } from "lucide-react"
import { Button } from "@/components/ui/button"

export interface PaginationBarProps {
  page: number
  totalPages: number
  total: number
  pageSize?: number
  /** "page" = 第 x/y 页模式 (page is 1-based). "offset" = 第 a-b 条模式 (page is 0-based). */
  mode?: "page" | "offset"
  onPageChange: (page: number) => void
}

export default function PaginationBar({
  page,
  totalPages,
  total,
  pageSize = 20,
  mode = "page",
  onPageChange,
}: PaginationBarProps) {
  if (totalPages <= 1 && total <= 0) return null

  const summary =
    mode === "offset"
      ? `第 ${page * pageSize + 1}-${Math.min((page + 1) * pageSize, total)} 条，共 ${total} 条`
      : `第 ${page} / ${totalPages} 页 · 共 ${total} 条`

  const prevDisabled = mode === "offset" ? page === 0 : page <= 1
  const nextDisabled = mode === "offset" ? (page + 1) * pageSize >= total : page >= totalPages

  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-muted-foreground">{summary}</span>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={prevDisabled}
          onClick={() => onPageChange(page - 1)}
          className="h-7 text-xs"
        >
          <ChevronLeftIcon className="h-3.5 w-3.5" />
          上一页
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={nextDisabled}
          onClick={() => onPageChange(page + 1)}
          className="h-7 text-xs"
        >
          下一页
          <ChevronRightIcon className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
