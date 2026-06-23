"""Public API routes — no authentication required.

IMPORTANT — deferred to follow-up refactoring:
  Current api_server.py routes are defined as closures inside create_app(),
  capturing _store and other module-level state from the closure scope.
  Full extraction requires:
  1. Move shared state (_store, _target_stores, cache dicts, etc.)
     to a dedicated ApplicationContext dataclass
  2. Convert create_app() inner functions to module-level handlers
     that accept ApplicationContext via dependency injection
  3. Then extract handlers to this module

Route inventory (for reference):
  GET  /api/v1/health          — health check
  GET  /                         — frontend SPA shell
  GET  /robots.txt               — SEO
  GET  /llms.txt                 — LLM discovery
  GET  /sitemap.xml              — SEO sitemap
  GET  /api/v1/targets           — public target list
  GET  /api/v1/regions           — public region list
  GET  /api/v1/public/news       — public news feed
  GET  /api/v1/public/news/{id}  — single public event
  GET  /api/v1/public/facets     — public filter facets
  GET  /api/v1/public/bootstrap  — public bootstrap data
  GET  /api/v1/stats             — public statistics
  GET  /api/v1/sources/health    — public source health
"""

from fastapi import APIRouter

router = APIRouter()

# Routes defined inline in create_app() — see api_server.py §公开端点
