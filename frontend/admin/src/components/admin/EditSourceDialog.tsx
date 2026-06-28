import { useState } from "react"
import { Loader2Icon } from "lucide-react"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { patchSource, type SourceInventoryItem, type SourcePatchRequest } from "@/lib/api"

interface EditSourceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  targetId: string
  item: SourceInventoryItem
  onSaved: () => void
}

const CREDIBILITY_OPTIONS = [
  { label: "高 (0.90)", value: 0.9 },
  { label: "中 (0.75)", value: 0.75 },
  { label: "低 (0.50)", value: 0.5 },
]

export default function EditSourceDialog({
  open,
  onOpenChange,
  targetId,
  item,
  onSaved,
}: EditSourceDialogProps) {
  const initialName = item.display_name ?? item.name ?? ""
  const initialUrl = item.url ?? ""
  const initialEnabled = item.enabled ?? !item.archived
  const initialCredibility = item.credibility_base ?? 0.75

  // Note: fetch_interval_minutes, max_items_per_run, timeout_seconds, notes
  // are NOT in inventory response -- always start blank
  const [displayName, setDisplayName] = useState(initialName)
  const [url, setUrl] = useState(initialUrl)
  const [enabled, setEnabled] = useState(initialEnabled)
  const [notes, setNotes] = useState("")
  const [credibilityBase, setCredibilityBase] = useState(initialCredibility)
  const [fetchInterval, setFetchInterval] = useState("")
  const [maxItems, setMaxItems] = useState("")
  const [timeoutSec, setTimeoutSec] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const payload: SourcePatchRequest = {}
      if (displayName !== initialName) payload.display_name = displayName
      if (url !== initialUrl) payload.url = url
      if (enabled !== initialEnabled) payload.enabled = enabled
      if (notes) payload.notes = notes
      if (credibilityBase !== initialCredibility) payload.credibility_base = credibilityBase
      if (fetchInterval) payload.fetch_interval_minutes = Number(fetchInterval)
      if (maxItems) payload.max_items_per_run = Number(maxItems)
      if (timeoutSec) payload.timeout_seconds = Number(timeoutSec)

      if (Object.keys(payload).length === 0) {
        onOpenChange(false)
        return
      }

      await patchSource(targetId, item.source_ref ?? item.source_id, payload)
      onSaved()
      onOpenChange(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>编辑信源</DialogTitle>
          <DialogDescription>
            修改 {item.display_name ?? item.name ?? item.source_id} 的配置
          </DialogDescription>
        </DialogHeader>

        {error && (
          <p className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">{error}</p>
        )}

        <div className="space-y-4">
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">显示名称</label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={saving}
            />
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">URL</label>
            <Input
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={saving}
            />
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">启用</label>
            <div className="flex items-center gap-2">
              <Input
                type="checkbox"
                className="h-4 w-4"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                disabled={saving}
              />
              <label className="text-sm text-muted-foreground">启用</label>
            </div>
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">备注</label>
            <textarea
              className="flex h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={saving}
            />
          </div>

          <hr className="my-3" />
          <p className="text-sm font-medium text-muted-foreground">采集参数</p>

          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">可信度</label>
            <select
              className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              value={credibilityBase}
              onChange={(e) => setCredibilityBase(Number(e.target.value))}
              disabled={saving}
            >
              {CREDIBILITY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">采集间隔</label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                className="w-24"
                value={fetchInterval}
                onChange={(e) => setFetchInterval(e.target.value)}
                min={1}
                disabled={saving}
                placeholder="30"
              />
              <span className="text-sm text-muted-foreground">分钟</span>
            </div>
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">最大条目</label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                className="w-24"
                value={maxItems}
                onChange={(e) => setMaxItems(e.target.value)}
                min={1}
                disabled={saving}
                placeholder="20"
              />
              <span className="text-sm text-muted-foreground">条/次</span>
            </div>
          </div>
          <div className="grid grid-cols-[100px_1fr] items-center gap-4">
            <label className="text-sm font-medium">超时</label>
            <div className="flex items-center gap-2">
              <Input
                type="number"
                className="w-24"
                value={timeoutSec}
                onChange={(e) => setTimeoutSec(e.target.value)}
                min={1}
                max={300}
                disabled={saving}
                placeholder="20"
              />
              <span className="text-sm text-muted-foreground">秒</span>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Loader2Icon className="mr-2 h-4 w-4 animate-spin" />}
            {saving ? "保存中..." : "保存"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
