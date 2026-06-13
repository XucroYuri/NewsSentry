#!/usr/bin/env python3
"""Verify public-site SEO/GEO discoverability surfaces."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_HOMEPAGE_PATH = "/public-app"
EXPECTED_HOMEPAGE_CANONICAL_PATH = "/public-app/"


@dataclass
class ResourceSnapshot:
    path: str
    url: str
    status_code: int
    headers: dict[str, str]
    text: str
    error: str | None = None


class _HeadSnapshotParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str = ""
        self.meta_name: dict[str, str] = {}
        self.meta_property: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.json_ld: list[dict[str, Any]] = []
        self._in_title = False
        self._json_ld_buffer: list[str] = []
        self._current_script_is_json_ld = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): (value or "") for key, value in attrs}
        lowered_tag = tag.lower()
        if lowered_tag == "title":
            self._in_title = True
            return
        if lowered_tag == "meta":
            content = attr_map.get("content", "")
            if attr_map.get("name"):
                self.meta_name[attr_map["name"]] = content
            if attr_map.get("property"):
                self.meta_property[attr_map["property"]] = content
            return
        if lowered_tag == "link" and attr_map.get("rel"):
            self.links[attr_map["rel"]] = attr_map.get("href", "")
            return
        if lowered_tag == "script" and attr_map.get("type", "").lower() == "application/ld+json":
            self._current_script_is_json_ld = True
            self._json_ld_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._current_script_is_json_ld:
            self._json_ld_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        lowered_tag = tag.lower()
        if lowered_tag == "title":
            self._in_title = False
            self.title = self.title.strip()
            return
        if lowered_tag == "script" and self._current_script_is_json_ld:
            raw_payload = "".join(self._json_ld_buffer).strip()
            self._current_script_is_json_ld = False
            self._json_ld_buffer = []
            if not raw_payload:
                return
            try:
                parsed = json.loads(raw_payload)
            except json.JSONDecodeError:
                return
            if isinstance(parsed, dict):
                self.json_ld.append(parsed)
            elif isinstance(parsed, list):
                self.json_ld.extend(item for item in parsed if isinstance(item, dict))


def normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def build_check(
    name: str,
    ok: bool,
    *,
    detail: str,
    severity: str = "error",
) -> dict[str, Any]:
    return {
        "name": name,
        "ok": ok,
        "severity": severity,
        "detail": detail,
    }


def extract_head_snapshot(html: str) -> dict[str, Any]:
    parser = _HeadSnapshotParser()
    parser.feed(html)
    return {
        "title": parser.title,
        "meta_name": dict(sorted(parser.meta_name.items())),
        "meta_property": dict(sorted(parser.meta_property.items())),
        "links": dict(sorted(parser.links.items())),
        "json_ld": parser.json_ld,
    }


def fetch_resource(
    client: httpx.Client,
    *,
    base_url: str,
    path: str,
) -> ResourceSnapshot:
    url = urljoin(f"{normalize_base_url(base_url)}/", path.lstrip("/"))
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        return ResourceSnapshot(
            path=path,
            url=url,
            status_code=0,
            headers={},
            text="",
            error=str(exc),
        )
    return ResourceSnapshot(
        path=path,
        url=str(response.url),
        status_code=response.status_code,
        headers={key.lower(): value for key, value in response.headers.items()},
        text=response.text,
    )


def build_text_resource_checks(
    snapshot: ResourceSnapshot,
    *,
    prefix: str,
    expected_content_type: str,
    required_fragments: list[str],
) -> list[dict[str, Any]]:
    checks = [
        build_check(
            f"{prefix}_status_ok",
            snapshot.status_code == 200,
            detail=snapshot.error or f"status_code={snapshot.status_code}",
        ),
        build_check(
            f"{prefix}_content_type_ok",
            expected_content_type in snapshot.headers.get("content-type", ""),
            detail=snapshot.headers.get("content-type", "<missing>"),
        ),
    ]
    for fragment in required_fragments:
        fragment_name = _slugify_check_fragment(fragment)
        checks.append(
            build_check(
                f"{prefix}_contains_{fragment_name}",
                fragment in snapshot.text,
                detail=f"fragment={fragment}",
            )
        )
    return checks


def parse_sitemap(snapshot: ResourceSnapshot) -> tuple[bool, list[str], str]:
    body = snapshot.text.strip()
    if not body:
        return False, [], "empty body"
    is_urlset = bool(re.search(r"<(?:\w+:)?urlset\b", body))
    urls = re.findall(r"<(?:\w+:)?loc>(.*?)</(?:\w+:)?loc>", body, flags=re.DOTALL)
    return is_urlset, [url.strip() for url in urls], "urlset" if is_urlset else "missing <urlset>"


def build_sitemap_checks(snapshot: ResourceSnapshot, *, base_url: str) -> list[dict[str, Any]]:
    checks = build_text_resource_checks(
        snapshot,
        prefix="sitemap",
        expected_content_type="xml",
        required_fragments=[],
    )
    is_urlset, urls, detail = parse_sitemap(snapshot)
    checks.append(
        build_check(
            "sitemap_parses_as_urlset",
            is_urlset,
            detail=detail,
        )
    )
    checks.append(
        build_check(
            "sitemap_urls_match_site_origin",
            bool(is_urlset and urls)
            and all(url.startswith(normalize_base_url(base_url)) for url in urls),
            detail=f"url_count={len(urls)}; parsed={is_urlset}",
        )
    )
    return checks


def build_homepage_checks(snapshot: ResourceSnapshot, *, base_url: str) -> list[dict[str, Any]]:
    head = extract_head_snapshot(snapshot.text)
    expected_canonical = f"{normalize_base_url(base_url)}{EXPECTED_HOMEPAGE_CANONICAL_PATH}"
    canonical_url = head["links"].get("canonical", "")
    json_ld_blocks = head["json_ld"]
    has_schema_context = any(
        str(block.get("@context", "")).startswith("https://schema.org")
        or str(block.get("@context", "")).startswith("http://schema.org")
        for block in json_ld_blocks
    )
    return [
        build_check(
            "homepage_status_ok",
            snapshot.status_code == 200,
            detail=snapshot.error or f"status_code={snapshot.status_code}",
        ),
        build_check(
            "homepage_content_type_html",
            "text/html" in snapshot.headers.get("content-type", ""),
            detail=snapshot.headers.get("content-type", "<missing>"),
        ),
        build_check(
            "homepage_title_present",
            bool(head["title"].strip()),
            detail=head["title"] or "<missing>",
        ),
        build_check(
            "homepage_meta_description_present",
            bool(head["meta_name"].get("description")),
            detail=head["meta_name"].get("description", "<missing>"),
        ),
        build_check(
            "homepage_og_title_present",
            bool(head["meta_property"].get("og:title")),
            detail=head["meta_property"].get("og:title", "<missing>"),
        ),
        build_check(
            "homepage_og_description_present",
            bool(head["meta_property"].get("og:description")),
            detail=head["meta_property"].get("og:description", "<missing>"),
        ),
        build_check(
            "homepage_canonical_matches_expected",
            canonical_url == expected_canonical,
            detail=canonical_url or "missing canonical",
        ),
        build_check(
            "homepage_json_ld_present",
            bool(json_ld_blocks),
            detail=f"json_ld_blocks={len(json_ld_blocks)}",
        ),
        build_check(
            "homepage_json_ld_uses_schema_org",
            has_schema_context,
            detail=(
                "schema.org context found"
                if has_schema_context
                else "missing schema.org context"
            ),
        ),
    ]


def summarize_checks(base_url: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [check for check in checks if not check["ok"]]
    return {
        "schema_version": 1,
        "base_url": normalize_base_url(base_url),
        "ok": not failed,
        "counts": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "failed_checks": [check["name"] for check in failed],
        "checks": checks,
    }


def _slugify_check_fragment(fragment: str) -> str:
    lowered = fragment.lower().replace("https://", "").replace("http://", "")
    slug = re.sub(r"[^a-z0-9]+", "_", lowered)
    return slug.strip("_")


def verify_public_site(
    base_url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    normalized_base_url = normalize_base_url(base_url)
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        robots = fetch_resource(client, base_url=normalized_base_url, path="/robots.txt")
        llms = fetch_resource(client, base_url=normalized_base_url, path="/llms.txt")
        sitemap = fetch_resource(client, base_url=normalized_base_url, path="/sitemap.xml")
        homepage = fetch_resource(client, base_url=normalized_base_url, path=DEFAULT_HOMEPAGE_PATH)

    checks = [
        *build_text_resource_checks(
            robots,
            prefix="robots",
            expected_content_type="text/plain",
            required_fragments=[
                "User-agent:",
                f"Sitemap: {normalized_base_url}/sitemap.xml",
            ],
        ),
        *build_text_resource_checks(
            llms,
            prefix="llms",
            expected_content_type="text/plain",
            required_fragments=[
                "News Sentry",
                "/public-app",
                "/sitemap.xml",
            ],
        ),
        *build_sitemap_checks(sitemap, base_url=normalized_base_url),
        *build_homepage_checks(homepage, base_url=normalized_base_url),
    ]
    report = summarize_checks(normalized_base_url, checks)
    report["resources"] = {
        "robots": {"path": robots.path, "url": robots.url, "status_code": robots.status_code},
        "llms": {"path": llms.path, "url": llms.url, "status_code": llms.status_code},
        "sitemap": {"path": sitemap.path, "url": sitemap.url, "status_code": sitemap.status_code},
        "homepage": {
            "path": homepage.path,
            "url": homepage.url,
            "status_code": homepage.status_code,
        },
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify public-site SEO/GEO surfaces.")
    parser.add_argument("--base-url", required=True, help="Base URL such as https://news-sentry.com")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", help="Optional JSON output path.")
    args = parser.parse_args()

    report = verify_public_site(args.base_url, timeout_seconds=args.timeout_seconds)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
