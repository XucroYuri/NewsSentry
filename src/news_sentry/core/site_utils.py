"""Site utility helpers — static files, SPA routing, security headers, sitemap, SEO, git metadata.

Extracted from api_server.py module-level functions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

import news_sentry.core._state as _st
from news_sentry.core._state import (
    _PUBLIC_APP_SHELL_CACHE_CONTROL,
    _PUBLIC_SITE_BASE_URL,
    _PUBLIC_SITE_DESCRIPTION,
    _PUBLIC_SITE_DESCRIPTION_IT,
    _PUBLIC_SITE_NAME,
    _PUBLIC_SITE_TITLE,
    _PUBLIC_SITE_TITLE_IT,
)
from news_sentry.core.public_news_utils import _public_news_target_ids

logger = logging.getLogger(__name__)

# ── Late-bound (assigned by api_server after import) ──
_get_target_store: Any = None
SitemapEntry: Any = None
PublicSiteProjectionStore: Any = None


_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains; preload",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"
    ),
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net https://static.cloudflareinsights.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://cloudflareinsights.com https://static.cloudflareinsights.com; "
        "base-uri 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "object-src 'none'"
    ),
}


def _security_headers_with_script_nonce(nonce: str) -> dict[str, str]:
    headers = dict(_SECURITY_HEADERS)
    headers["Content-Security-Policy"] = _SECURITY_HEADERS["Content-Security-Policy"].replace(
        "script-src 'self'",
        f"script-src 'self' 'nonce-{nonce}'",
    )
    return headers

_SCRIPT_TAG_WITHOUT_NONCE_RE = re.compile(r"<script(?![^>]*\bnonce=)", re.IGNORECASE)


def _inject_script_nonce(html: str, nonce: str) -> str:
    return _SCRIPT_TAG_WITHOUT_NONCE_RE.sub(f'<script nonce="{nonce}"', html)



def _inject_inline_css(html: str, nonce: str) -> str:
    """读取 dist/assets/ 下的 CSS 文件并内联到 <style nonce> 标签中。

    消除首屏 FOUC（flash of unstyled content），让 critical CSS 与 HTML 一同抵达。
    内联的 <style> 与外部 <link> 共存 -- 浏览器优先使用内联样式，外部 link 作为缓存策略。
    """
    dist_dir = _public_app_dir() / "assets"
    if not dist_dir.is_dir():
        return html

    css_files = sorted(dist_dir.glob("index-*.css"))
    if not css_files:
        return html

    css_path = css_files[0]  # Vite 构建产物通常只有一个 index-{hash}.css
    try:
        css_content = css_path.read_text(encoding="utf-8")
    except OSError:
        return html

    # 在 </head> 前插入内联 style 标签
    style_tag = f"\n<style nonce=\"{nonce}\">{css_content}</style>\n"
    if "</head>" in html:
        html = html.replace("</head>", f"{style_tag}</head>", 1)
    else:
        html = f"{style_tag}\n{html}"

    return html

def _static_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "static"



def _static_build_hash(static_dir: Path | None = None) -> str:
    """基于 admin + public_app 构建产物计算散列，用于 health/metrics 端点。"""
    static_root = static_dir or _static_dir()
    digest = sha256()
    files_seen = 0
    manifests_to_hash = [
        static_root / "admin" / "index.html",
        static_root / "public_app" / "index.html",
    ]
    for path in manifests_to_hash:
        if not path.is_file():
            continue
        digest.update(str(path.relative_to(static_root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
        files_seen += 1
    return digest.hexdigest()[:12] if files_seen else "development"



def _index_html_response() -> HTMLResponse:
    index_path = _static_dir() / "admin" / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Admin app not built")
    nonce = secrets.token_urlsafe(16)
    html = index_path.read_text(encoding="utf-8").replace("__CSP_NONCE__", nonce)
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": _PUBLIC_APP_SHELL_CACHE_CONTROL,
        },
    )



def _public_app_dir(static_dir: Path | None = None) -> Path:
    return (static_dir or _static_dir()) / "public_app"



def _frontend_public_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "frontend" / "public" / "public"



def _public_discoverability_asset_path(filename: str) -> Path:
    candidates = (
        _frontend_public_dir() / filename,
        _static_dir() / filename,
        _public_app_dir() / filename,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail=f"{filename} not found")



def _public_discoverability_text(filename: str) -> str:
    return _public_discoverability_asset_path(filename).read_text(encoding="utf-8")



def _public_site_base_url(request: Request | None = None) -> str:
    configured = os.environ.get("NEWSSENTRY_PUBLIC_SITE_BASE_URL")
    if configured:
        return configured.rstrip("/")
    if request is not None:
        host = request.headers.get("host", "").strip().lower()
        if host in {"news-sentry.com", "preview.news-sentry.com"}:
            return f"{request.url.scheme}://{host}"
    return _PUBLIC_SITE_BASE_URL.rstrip("/")



async def _render_public_sitemap_xml(store: Any, *, base_url: str) -> str:
    try:
        entries = await _public_sitemap_entries(base_url=base_url)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to collect public sitemap entries")
        entries = [
            SitemapEntry(
                loc=f"{base_url}/",
                lastmod=datetime.now(UTC).isoformat(),
            )
        ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in entries:
        try:
            loc = str(entry.loc).strip()
            lastmod = str(entry.lastmod).strip()
        except Exception:  # noqa: BLE001
            logger.exception("Failed to normalize sitemap entry")
            continue
        if not loc or not lastmod:
            continue
        lines.extend(
            [
                "  <url>",
                f"    <loc>{xml_escape(loc)}</loc>",
                f"    <lastmod>{xml_escape(lastmod)}</lastmod>",
                "  </url>",
            ]
        )
    lines.append("</urlset>")
    return "\n".join(lines)



async def _public_sitemap_entries(*, base_url: str) -> list[Any]:
    entries: list[Any] = []
    if _st._store is not None:
        projection_store = PublicSiteProjectionStore(_st._store, base_url=base_url)
        try:
            entries = await projection_store.list_sitemap_entries(limit=1000)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to render sitemap entries from global store")
            entries = []
        if entries:
            return entries
    for target_id in _public_news_target_ids(_st._data_dir, None):
        try:
            store = await _get_target_store(target_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to open target store for sitemap target %s", target_id)
            continue
        if store is None:
            continue
        projection_store = PublicSiteProjectionStore(store, base_url=base_url)
        try:
            entries.extend(
                await projection_store.list_sitemap_entries(target_id=target_id, limit=1000)
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to render sitemap entries for target %s", target_id)
    if entries:
        return entries
    return [
        SitemapEntry(
            loc=f"{base_url}/",
            lastmod=datetime.now(UTC).isoformat(),
        )
    ]



def _public_app_page_copy(canonical_path: str, locale: str = "zh") -> tuple[str, str]:
    """返回页面 SEO 标题和描述，根据 locale 返回对应语言。"""
    it = locale == "it"
    if canonical_path == "/sources":
        return (
            "来源目录" if not it else "Directory delle Fonti",
            (
                "按公开新闻聚合媒体与信源，帮助读者理解 News Sentry 新闻来自哪里。"
                if not it
                else "Esplora le fonti giornalistiche e i media aggregati "
                "da cui News Sentry attinge le notizie."
            ),
        )
    if canonical_path == "/subscribe":
        return (
            "订阅 Subscribe" if not it else "Iscriviti",
            (
                "接收 News Sentry 每日信号、新闻日报与目标更新。"
                if not it
                else "Ricevi i segnali quotidiani, il bollettino e gli aggiornamenti "
                "sui target di News Sentry."
            ),
        )
    return (
        (_PUBLIC_SITE_TITLE, _PUBLIC_SITE_DESCRIPTION)
        if not it
        else (_PUBLIC_SITE_TITLE_IT, _PUBLIC_SITE_DESCRIPTION_IT)
    )



def _inject_public_homepage_seo(
    html: str,
    *,
    base_url: str,
    canonical_path: str = "/public-app/",
    locale: str = "zh",
) -> str:
    """注入 SEO 元标签（canonical、hreflang、OG、Twitter Card、JSON-LD）及 html lang 属性。

    根据 locale 注入对应语言：
    - "zh" → lang="zh-CN"（中文站）
    - "it" → lang="it"（意大利语站）
    """
    # 设置 <html lang> 属性
    html_lang = "it" if locale == "it" else "zh-CN"
    if "<html" in html:
        if 'lang=' in html[:200]:
            html = re.sub(r'lang="[^"]*"', f'lang="{html_lang}"', html, count=1)
        else:
            html = re.sub(r"(<html[^>]*)>", rf'\1 lang="{html_lang}">', html, count=1)

    canonical_url = f"{base_url}{canonical_path}"
    page_name, description = _public_app_page_copy(canonical_path, locale)
    json_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": page_name,
            "description": description,
            "url": canonical_url,
            "inLanguage": html_lang,
            "isPartOf": {
                "@type": "WebSite",
                "name": _PUBLIC_SITE_NAME,
                "url": f"{base_url}/public-app/",
            },
        },
        ensure_ascii=False,
    )
    tags: list[str] = []
    # meta description（覆盖前端硬编码的中文描述）
    if 'name="description"' not in html:
        tags.append(f'    <meta name="description" content="{description}" />')
    # canonical
    if 'rel="canonical"' not in html:
        tags.append(f'    <link rel="canonical" href="{canonical_url}" />')
    # hreflang alternate（告知搜索引擎双语版本）
    if 'hreflang="zh-CN"' not in html:
        tags.append(
            f'    <link rel="alternate" hreflang="zh-CN" href="{base_url}/public-app/" />'
        )
        tags.append(
            f'    <link rel="alternate" hreflang="it" href="{base_url}/public-app/it/" />'
        )
        tags.append(
            f'    <link rel="alternate" hreflang="x-default" href="{base_url}/public-app/" />'
        )
    # Open Graph
    if 'property="og:title"' not in html:
        tags.append(f'    <meta property="og:title" content="{page_name}" />')
    if 'property="og:description"' not in html:
        tags.append(f'    <meta property="og:description" content="{description}" />')
    if 'property="og:url"' not in html:
        tags.append(f'    <meta property="og:url" content="{canonical_url}" />')
    if 'property="og:locale"' not in html:
        og_locale = "it_IT" if locale == "it" else "zh_CN"
        tags.append(f'    <meta property="og:locale" content="{og_locale}" />')
    if 'property="og:locale:alternate"' not in html:
        alt_og_locale = "zh_CN" if locale == "it" else "it_IT"
        tags.append(
            f'    <meta property="og:locale:alternate" content="{alt_og_locale}" />'
        )
    if 'property="og:image"' not in html:
        tags.append(
            f'    <meta property="og:image" content="{base_url}/icons/icon-192.svg" />'
        )
        tags.append(
            f'    <meta property="og:image:alt" content="{_PUBLIC_SITE_NAME} logo" />'
        )
        tags.append('    <meta property="og:image:width" content="192" />')
        tags.append('    <meta property="og:image:height" content="192" />')
    # Twitter Card
    if 'name="twitter:card"' not in html:
        tags.append('    <meta name="twitter:card" content="summary" />')
    if 'name="twitter:title"' not in html:
        tags.append(f'    <meta name="twitter:title" content="{page_name}" />')
    if 'name="twitter:description"' not in html:
        tags.append(f'    <meta name="twitter:description" content="{description}" />')
    if 'name="twitter:image"' not in html:
        tags.append(
            f'    <meta name="twitter:image" content="{base_url}/icons/icon-192.svg" />'
        )
    # JSON-LD
    if "application/ld+json" not in html:
        tags.append(f'    <script type="application/ld+json">{json_ld}</script>')
    if not tags:
        return html
    injected = "\n" + "\n".join(tags) + "\n"
    if "</head>" not in html:
        if "<html" in html and ">" in html:
            return re.sub(
                r"(<html[^>]*>)",
                lambda match: f"{match.group(1)}<head>{injected}</head>",
                html,
                count=1,
            )
        return f"<head>{injected}</head>{html}"
    return html.replace("</head>", f"{injected}  </head>", 1)



def _public_app_index_response(
    *,
    base_url: str | None = None,
    canonical_path: str = "/public-app/",
    bootstrap_json: str | None = None,
    feed_json: str | None = None,
    locale: str = "zh",
) -> HTMLResponse:
    index_path = _public_app_dir() / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=404, detail="Public app not built")
    nonce = secrets.token_urlsafe(16)
    html = index_path.read_text(encoding="utf-8")
    if base_url:
        html = _inject_public_homepage_seo(
            html,
            base_url=base_url,
            canonical_path=canonical_path,
            locale=locale,
        )
    # 内联 critical CSS：读取 dist/assets/ 下的 CSS 文件，注入到 <style nonce> 标签
    html = _inject_inline_css(html, nonce)
    hydration_tags: list[str] = []
    if bootstrap_json:
        hydration_tags.append(
            f'<script id="news-sentry-bootstrap" type="application/json">'
            f"{bootstrap_json}</script>"
        )
    if feed_json:
        hydration_tags.append(
            f'<script id="news-sentry-feed" type="application/json">{feed_json}</script>'
        )
    if hydration_tags:
        hydration_html = "\n" + "\n".join(hydration_tags) + "\n"
        if "</head>" in html:
            html = html.replace("</head>", f"{hydration_html}</head>", 1)
        else:
            html = f"{hydration_html}\n{html}"
    html = _inject_script_nonce(html, nonce)
    return HTMLResponse(
        html,
        headers={
            **_security_headers_with_script_nonce(nonce),
            "Cache-Control": _PUBLIC_APP_SHELL_CACHE_CONTROL,
        },
    )



def _public_app_asset_response(
    asset_path: str,
    *,
    base_url: str | None = None,
    canonical_path: str = "/public-app/",
    locale: str = "zh",
) -> Response:
    public_root = _public_app_dir().resolve()
    clean_asset_path = asset_path.strip("/")
    if not clean_asset_path:
        return _public_app_index_response(
            base_url=base_url, canonical_path=canonical_path, locale=locale
        )
    file_path = (public_root / clean_asset_path).resolve()
    try:
        file_path.relative_to(public_root)
    except ValueError:
        raise HTTPException(status_code=404, detail="Static asset not found") from None
    if file_path.is_file():
        cache_control = (
            "public, max-age=31536000, immutable"
            if clean_asset_path.startswith("assets/")
            else _PUBLIC_APP_SHELL_CACHE_CONTROL
        )
        return FileResponse(file_path, headers={"Cache-Control": cache_control})
    if clean_asset_path.startswith("assets/"):
        raise HTTPException(status_code=404, detail="Static asset not found")
    return _public_app_index_response(
        base_url=base_url, canonical_path=canonical_path, locale=locale
    )



def _git_dir_for_path(path: Path) -> Path | None:
    for parent in [path.resolve(), *path.resolve().parents]:
        dot_git = parent / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            try:
                content = dot_git.read_text(encoding="utf-8").strip()
            except OSError:
                return None
            if content.startswith("gitdir:"):
                git_dir = Path(content.split(":", 1)[1].strip())
                return git_dir if git_dir.is_absolute() else (parent / git_dir).resolve()
    return None



def _git_commit_for_path(path: Path) -> str:
    git_dir = _git_dir_for_path(path)
    if git_dir is None:
        return os.environ.get("NEWS_SENTRY_GIT_COMMIT", "unknown")
    try:
        common_dir_path = git_dir / "commondir"
        common_dir = (
            (git_dir / common_dir_path.read_text(encoding="utf-8").strip()).resolve()
            if common_dir_path.is_file()
            else git_dir
        )
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            for ref_path in (git_dir / ref, common_dir / ref):
                if ref_path.is_file():
                    return ref_path.read_text(encoding="utf-8").strip()[:12]
            return "unknown"
        return head[:12]
    except OSError:
        return os.environ.get("NEWS_SENTRY_GIT_COMMIT", "unknown")



def _mount_spa_routes(app: FastAPI) -> None:
    """挂载 SPA 静态资源与服务路由。"""

    static_dir = _static_dir()
    if static_dir.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
