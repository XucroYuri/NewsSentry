import { useEffect, useState, useCallback } from "react"
import {
  BellIcon,
  BellOffIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  Trash2Icon,
} from "lucide-react"

import {
  fetchNotificationRules,
  upsertNotificationRule,
  deleteNotificationRule,
  type NotificationRuleInfo,
  type NotificationRuleRequest,
} from "@/lib/api"
import { Card, CardContent } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { sentimentLabel } from "@/lib/utils"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

const DEFAULT_TARGET_IDS = ["italy", "france", "germany", "uk", "us", "japan"]
const ENTITY_SUGGESTIONS = ["meloni", "mattarella", "salvini", "conte", "schlein", "macron", "scholz"]
const SENTIMENT_OPTIONS = ["positive", "negative", "neutral", "very_negative"]

export default function NotificationsPage() {
  const [rules, setRules] = useState<NotificationRuleInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Edit dialog state
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<Partial<NotificationRuleRequest> | null>(null)
  const [saving, setSaving] = useState(false)
  const [dialogError, setDialogError] = useState<string | null>(null)

  const loadRules = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchNotificationRules()
      setRules(data.rules ?? [])
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadRules()
  }, [loadRules])

  function openCreate() {
    setEditingRule({
      id: "",
      user_id: "",
      watch: { target_ids: [], entities: [], min_value_score: 0, sentiment: [] },
      action: { channels: ["browser"], throttle_seconds: 1800 },
      quiet_hours: null,
      enabled: true,
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  function openEdit(rule: NotificationRuleInfo) {
    const r = rule.rule as Record<string, unknown>
    const watch = (r.watch ?? {}) as Record<string, unknown>
    const action = (r.action ?? {}) as Record<string, unknown>
    setEditingRule({
      id: String(r.id ?? rule.id),
      user_id: String(r.user_id ?? rule.user_id),
      watch: {
        target_ids: (watch.target_ids ?? []) as string[],
        entities: (watch.entities ?? []) as string[],
        min_value_score: Number(watch.min_value_score ?? 0),
        sentiment: (watch.sentiment ?? []) as string[],
      },
      action: {
        channels: (action.channels ?? ["browser"]) as string[],
        throttle_seconds: Number(action.throttle_seconds ?? 1800),
      },
      quiet_hours: (r.quiet_hours ?? null) as Record<string, unknown> | null,
      enabled: Boolean(rule.enabled),
    })
    setDialogError(null)
    setDialogOpen(true)
  }

  async function handleSave() {
    if (!editingRule) return
    if (!editingRule.id?.trim()) {
      setDialogError("规则 ID 不能为空")
      return
    }
    setSaving(true)
    setDialogError(null)
    try {
      await upsertNotificationRule(editingRule as NotificationRuleRequest)
      setDialogOpen(false)
      await loadRules()
    } catch (e) {
      setDialogError(e instanceof Error ? e.message : "保存失败")
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete(ruleId: string) {
    if (!confirm(`确定删除规则 ${ruleId}？`)) return
    try {
      await deleteNotificationRule(ruleId)
      await loadRules()
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败")
    }
  }

  function toggleTargetId(targetId: string) {
    if (!editingRule) return
    const watch = editingRule.watch as Record<string, unknown>
    const current = (watch.target_ids ?? []) as string[]
    const next = current.includes(targetId)
      ? current.filter((t) => t !== targetId)
      : [...current, targetId]
    setEditingRule({
      ...editingRule,
      watch: { ...watch, target_ids: next },
    })
  }

  function toggleEntity(entity: string) {
    if (!editingRule) return
    const watch = editingRule.watch as Record<string, unknown>
    const current = (watch.entities ?? []) as string[]
    const next = current.includes(entity)
      ? current.filter((e) => e !== entity)
      : [...current, entity]
    setEditingRule({
      ...editingRule,
      watch: { ...watch, entities: next },
    })
  }

  function toggleSentiment(s: string) {
    if (!editingRule) return
    const watch = editingRule.watch as Record<string, unknown>
    const current = (watch.sentiment ?? []) as string[]
    const next = current.includes(s)
      ? current.filter((x) => x !== s)
      : [...current, s]
    setEditingRule({
      ...editingRule,
      watch: { ...watch, sentiment: next },
    })
  }

  const watch = (editingRule?.watch ?? {}) as Record<string, unknown>
  const action = (editingRule?.action ?? {}) as Record<string, unknown>

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">通知规则</h1>
          <p className="text-sm text-muted-foreground mt-1">
            配置实时告警规则：匹配新闻事件后通过浏览器推送通知
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={loadRules} disabled={loading}>
            <RefreshCwIcon className="h-4 w-4 mr-1" />
            刷新
          </Button>
          <Button size="sm" onClick={openCreate}>
            <PlusIcon className="h-4 w-4 mr-1" />
            新建规则
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : rules.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 text-muted-foreground">
            <BellOffIcon className="h-10 w-10 mb-3" />
            <p className="text-sm">暂无通知规则</p>
            <p className="text-xs mt-1">点击"新建规则"创建第一条告警规则</p>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rules.map((rule) => {
            const r = rule.rule as Record<string, unknown>
            const w = (r.watch ?? {}) as Record<string, unknown>
            const a = (r.action ?? {}) as Record<string, unknown>
            const targets = (w.target_ids ?? []) as string[]
            const entities = (w.entities ?? []) as string[]
            const minScore = Number(w.min_value_score ?? 0)
            const sentiments = (w.sentiment ?? []) as string[]
            const channels = (a.channels ?? ["browser"]) as string[]
            const throttle = Number(a.throttle_seconds ?? 1800)

            return (
              <Card key={rule.id}>
                <CardContent className="py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0 space-y-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-sm font-semibold">{rule.id}</span>
                        {rule.enabled ? (
                          <Badge variant="success" className="text-[10px]">已启用</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-[10px]">已禁用</Badge>
                        )}
                        <span className="text-xs text-muted-foreground">
                          用户: {rule.user_id || "(all)"}
                        </span>
                      </div>

                      {(targets.length > 0 || entities.length > 0 || minScore > 0 || sentiments.length > 0) && (
                        <div className="flex flex-wrap gap-1.5">
                          {targets.map((t) => (
                            <Badge key={t} variant="outline" className="text-[10px]">{t}</Badge>
                          ))}
                          {entities.map((e) => (
                            <Badge key={e} variant="outline" className="text-[10px] border-info/30">@{e}</Badge>
                          ))}
                          {minScore > 0 && (
                            <Badge variant="outline" className="text-[10px]">分值 &ge;{minScore}</Badge>
                          )}
                          {sentiments.map((s) => (
                            <Badge key={s} variant="outline" className="text-[10px]">{sentimentLabel(s)}</Badge>
                          ))}
                        </div>
                      )}

                      <div className="text-xs text-muted-foreground">
                        推送到 {channels.join(", ")} &middot; 去重 {throttle}s
                        {r.quiet_hours ? " &middot; 已启用静默时段" : ""}
                      </div>
                    </div>

                    <div className="flex items-center gap-1 shrink-0">
                      <Button variant="ghost" size="icon" onClick={() => openEdit(rule)}>
                        <BellIcon className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => handleDelete(rule.id)}
                        className="text-destructive hover:text-destructive"
                      >
                        <Trash2Icon className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* ── Edit/Create Dialog ── */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingRule?.id && rules.some((r) => r.id === editingRule.id)
                ? `编辑规则: ${editingRule.id}`
                : "新建通知规则"}
            </DialogTitle>
            <DialogDescription>
              配置触发条件和推送方式
            </DialogDescription>
          </DialogHeader>

          {editingRule && (
            <div className="space-y-4 py-2">
              {/* Rule ID */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium">规则 ID</label>
                <Input
                  value={editingRule.id ?? ""}
                  onChange={(e) => setEditingRule({ ...editingRule, id: e.target.value })}
                  placeholder="例如: italy-high-value"
                  disabled={!!editingRule.id && rules.some((r) => r.id === editingRule.id)}
                />
              </div>

              {/* Enable/Disable */}
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">启用</label>
                <input
                  type="checkbox"
                  checked={editingRule.enabled ?? true}
                  onChange={(e) => setEditingRule({ ...editingRule, enabled: e.target.checked })}
                  className="h-4 w-4 rounded border-border"
                />
              </div>

              {/* Target IDs */}
              <fieldset className="space-y-1.5 border rounded-md p-3">
                <legend className="text-sm font-medium px-1">监控目标</legend>
                <div className="flex flex-wrap gap-1.5">
                  {DEFAULT_TARGET_IDS.map((tid) => {
                    const active = ((watch.target_ids ?? []) as string[]).includes(tid)
                    return (
                      <Badge
                        key={tid}
                        variant={active ? "default" : "outline"}
                        className="cursor-pointer text-[11px]"
                        onClick={() => toggleTargetId(tid)}
                      >
                        {tid}
                      </Badge>
                    )
                  })}
                </div>
              </fieldset>

              {/* Entities */}
              <fieldset className="space-y-1.5 border rounded-md p-3">
                <legend className="text-sm font-medium px-1">实体过滤（可选，交集匹配）</legend>
                <div className="flex flex-wrap gap-1.5">
                  {ENTITY_SUGGESTIONS.map((ent) => {
                    const active = ((watch.entities ?? []) as string[]).includes(ent)
                    return (
                      <Badge
                        key={ent}
                        variant={active ? "default" : "outline"}
                        className="cursor-pointer text-[11px]"
                        onClick={() => toggleEntity(ent)}
                      >
                        {ent}
                      </Badge>
                    )
                  })}
                </div>
              </fieldset>

              {/* Min score */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium">最低价值分</label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={watch.min_value_score as number ?? 0}
                  onChange={(e) =>
                    setEditingRule({
                      ...editingRule,
                      watch: { ...watch, min_value_score: parseInt(e.target.value, 10) || 0 },
                    })
                  }
                />
              </div>

              {/* Sentiment */}
              <fieldset className="space-y-1.5 border rounded-md p-3">
                <legend className="text-sm font-medium px-1">情感过滤</legend>
                <div className="flex flex-wrap gap-1.5">
                  {SENTIMENT_OPTIONS.map((s) => {
                    const active = ((watch.sentiment ?? []) as string[]).includes(s)
                    return (
                      <Badge
                        key={s}
                        variant={active ? "default" : "outline"}
                        className="cursor-pointer text-[11px]"
                        onClick={() => toggleSentiment(s)}
                      >
                        {sentimentLabel(s)}
                      </Badge>
                    )
                  })}
                </div>
              </fieldset>

              {/* Throttle */}
              <div className="space-y-1.5">
                <label className="text-sm font-medium">去重窗口 (秒)</label>
                <Input
                  type="number"
                  min={0}
                  max={86400}
                  value={action.throttle_seconds as number ?? 1800}
                  onChange={(e) =>
                    setEditingRule({
                      ...editingRule,
                      action: { ...action, throttle_seconds: parseInt(e.target.value, 10) || 0 },
                    })
                  }
                />
              </div>

              {dialogError && (
                <div className="rounded-md bg-destructive/10 p-2 text-sm text-destructive">
                  {dialogError}
                </div>
              )}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving && <Loader2Icon className="h-4 w-4 mr-1 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
