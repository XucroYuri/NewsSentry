"""Admin API routes — authentication required.

IMPORTANT — deferred to follow-up refactoring:
  see api/routes/public.py for rationale. Same closure-in-create_app() issue.

Route inventory (for reference):
  POST /api/v1/auth/login
  POST /api/v1/auth/token
  POST /api/v1/auth/stream-token
  GET  /api/v1/auth/me
  POST /api/v1/auth/logout
  POST /api/v1/auth/change-password
  GET  /api/v1/auth/setup-status
  POST /api/v1/auth/setup
  GET  /api/v1/admin/users
  POST /api/v1/admin/users
  POST /api/v1/admin/users/{username}/reset-password
  GET  /api/v1/admin/targets
  POST /api/v1/admin/targets
  PATCH  /api/v1/admin/targets/{target_id}
  POST   /api/v1/admin/targets/{target_id}/archive
  POST   /api/v1/admin/targets/{target_id}/restore
  GET  /api/v1/admin/targets/{target_id}/overview
  POST /api/v1/admin/targets/{target_id}/validate
  GET  /api/v1/admin/targets/{target_id}/inventory
  GET  /api/v1/admin/targets/{target_id}/sources
  POST /api/v1/admin/targets/{target_id}/sources
  PATCH  /api/v1/admin/targets/{target_id}/sources/{source_ref}
  POST   /api/v1/admin/targets/{target_id}/sources/{source_ref}/archive
  (and ~30 more admin/config/collector/maintenance endpoints...)
"""

from fastapi import APIRouter

router = APIRouter()

# Routes defined inline in create_app() — see api_server.py
