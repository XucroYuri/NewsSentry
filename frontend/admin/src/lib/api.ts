/**
 * News Sentry Admin Console — API client
 *
 * 管理后台的 API 调用统一通过 BFF 层转发：
 * 组件 -> api.ts (本文件，re-export BFF) -> backend/src/backend/api/*.ts -> fetch()
 *
 * 本文件保留类型定义和 re-export，所有实现委托给 @backend/api/ 下的 BFF 函数。
 */

// ── Re-export BFF impls ──────────────────────────────

export { login as loginAdmin } from "@backend/api/auth"
export type { LoginResponse } from "@backend/api/auth"

export { fetchOverview as fetchAdminOverview } from "@backend/api/overview"
export type {
  AdminOverviewResponse,
  SourceHealthItem,
} from "@backend/api/overview"

export type { AdminTargetInfo } from "@backend/api/targets"
export type { RunLogEntry } from "@backend/api/diagnostics"

export {
  fetchTargets as fetchAdminTargets,
  createTarget,
  archiveTarget,
  restoreTarget,
} from "@backend/api/targets"
export type { AdminTargetListResponse, TargetCreateRequest } from "@backend/api/targets"

export { fetchInventory as fetchTargetInventory } from "@backend/api/inventory"
export type { SourceInventoryItem, SourceInventoryResponse } from "@backend/api/inventory"

export {
  patchSource,
  archiveSource,
  restoreSource,
  validateTarget,
} from "@backend/api/sources"
export type { SourcePatchRequest } from "@backend/api/sources"

export {
  fetchStatus as fetchCollectorStatus,
  start as startCollector,
  stop as stopCollector,
} from "@backend/api/collector"
export type { CollectorStatusResponse } from "@backend/api/collector"

export {
  fetchUsers as fetchAdminUsers,
  createUser as createAdminUser,
  deleteUser as deleteAdminUser,
  resetPassword as resetUserPassword,
} from "@backend/api/users"
export type { AdminUser, AdminUserListResponse } from "@backend/api/users"

export { fetchDiagnostics } from "@backend/api/diagnostics"
export type {
  DiagnosticsDeploy,
  DiagnosticsCollector,
  DiagnosticsData,
  DiagnosticsSourceHealth,
  DiagnosticsEvents,
  DiagnosticsResponse,
} from "@backend/api/diagnostics"

export {
  fetchRules as fetchNotificationRules,
  upsertRule as upsertNotificationRule,
  deleteRule as deleteNotificationRule,
} from "@backend/api/notifications"
export type {
  NotificationRuleRequest,
  NotificationRuleInfo,
  NotificationRuleListResponse,
} from "@backend/api/notifications"

export {
  fetchEntities,
  searchEntities,
  fetchEntity,
  fetchEntityEvents,
  mergeEntities,
} from "@backend/api/entities"
export type {
  EntityInfo,
  EntityListResponse,
  EntityDetailResponse,
  EntityMergeResponse,
} from "@backend/api/entities"

export {
  fetchAnnotations,
  createAnnotation,
  updateAnnotation,
  deleteAnnotation,
  reviewAnnotation,
} from "@backend/api/annotations"
export type {
  AnnotationInfo,
  AnnotationListResponse,
  AnnotationCreateRequest,
  AnnotationUpdateRequest,
} from "@backend/api/annotations"

// ── Legacy re-exports (used by existing page components) ─

export { AdminApiError, authHeaders } from "@backend/api/util"
