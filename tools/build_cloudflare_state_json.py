#!/usr/bin/env python3
"""Build CLOUDFLARE_STATE_JSON for the deployed surface audit."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from deployment_surface_security import build_cloudflare_state_findings, load_policy

RULESET_DETAIL_PHASES = {
    "http_ratelimit",
    "http_request_firewall_custom",
    "http_request_firewall_managed",
    "http_response_headers_transform",
}


class CloudflareStateError(RuntimeError):
    """Raised when Cloudflare state cannot be collected with current credentials."""


def _normalize_destination_path(uri: str) -> str:
    value = uri.strip()
    if not value:
        return ""
    if "://" not in value:
        value = f"https://{value}"
    parsed = urllib.parse.urlsplit(value)
    path = parsed.path or "/"
    if path.endswith("*"):
        path = path[:-1]
        if not path.endswith("/"):
            path = f"{path}/"
    return path


def _destination_covers_required(uri: str, required: str) -> bool:
    path = _normalize_destination_path(uri)
    if not path:
        return False
    if required.endswith("/"):
        return path == required or path.startswith(required) or required.startswith(path)
    return path == required


def _rule_text(rule: dict[str, Any]) -> str:
    return json.dumps(rule, ensure_ascii=False, sort_keys=True)


def _phase_rulesets(rulesets: list[dict[str, Any]], phases: set[str]) -> list[dict[str, Any]]:
    return [item for item in rulesets if str(item.get("phase", "")) in phases]


def build_state_from_payloads(
    *,
    policy: dict[str, Any],
    access_apps: list[dict[str, Any]],
    rulesets: list[dict[str, Any]],
    live_response_headers: dict[str, Any],
    access_read_ok: bool = True,
    access_write_ok: bool = True,
) -> dict[str, Any]:
    """Build the compact audit state from Cloudflare API payloads."""

    expected = policy["cloudflare_expected"]
    destinations = [
        str(destination.get("uri", ""))
        for app in access_apps
        for destination in app.get("destinations", [])
        if isinstance(destination, dict)
    ]
    protected_prefixes = sorted(
        required
        for required in expected["required_access_protected_prefixes"]
        if any(_destination_covers_required(uri, required) for uri in destinations)
    )

    header_names = {str(name).lower() for name in live_response_headers}
    response_headers = sorted(
        header
        for header in {str(item).lower() for item in expected["required_response_headers"]}
        if header in header_names
    )

    rate_rules = [
        rule
        for ruleset in _phase_rulesets(rulesets, {"http_ratelimit"})
        for rule in ruleset.get("rules", [])
        if isinstance(rule, dict)
    ]
    rate_limit_paths = sorted(
        path
        for path in expected["required_rate_limit_paths"]
        if any(path in _rule_text(rule) for rule in rate_rules)
    )

    waf_rules = [
        rule
        for ruleset in _phase_rulesets(
            rulesets,
            {
                "http_request_firewall_custom",
                "http_request_firewall_managed",
            },
        )
        for rule in ruleset.get("rules", [])
        if isinstance(rule, dict)
    ]
    waf_path_prefixes = sorted(
        prefix
        for prefix in expected["required_waf_path_prefixes"]
        if any(prefix in _rule_text(rule) for rule in waf_rules)
    )

    return {
        "access_read_ok": access_read_ok,
        "access_write_ok": access_write_ok,
        "protected_prefixes": protected_prefixes,
        "response_headers": response_headers,
        "rate_limit_paths": rate_limit_paths,
        "waf_path_prefixes": waf_path_prefixes,
    }


def _load_token_from_wrangler() -> str:
    try:
        completed = subprocess.run(  # noqa: S603
            ["wrangler", "auth", "token", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CloudflareStateError("unable to read Wrangler auth token") from exc
    payload = json.loads(completed.stdout)
    token = str(payload.get("token") or payload.get("accessToken") or "")
    if not token:
        raise CloudflareStateError("Wrangler auth token output did not include a token")
    return token


def _resolve_api_token(args: argparse.Namespace) -> str:
    token = args.api_token or os.getenv("CLOUDFLARE_API_TOKEN") or os.getenv("CF_API_TOKEN")
    if token:
        return token
    if not args.no_wrangler:
        return _load_token_from_wrangler()
    raise CloudflareStateError("missing Cloudflare API token")


def _api_get(token: str, path: str) -> Any:
    url = f"https://api.cloudflare.com/client/v4{path}"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "api.cloudflare.com":
        raise CloudflareStateError(f"refusing unexpected Cloudflare API URL: {url}")
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"success": False, "errors": [{"message": body[:200]}]}
        errors = payload.get("errors") or [{"message": f"HTTP {exc.code}"}]
        raise CloudflareStateError(f"{path} -> {errors}") from exc
    if payload.get("success") is not True:
        raise CloudflareStateError(f"{path} -> {payload.get('errors')}")
    return payload.get("result")


def _collect_rulesets(token: str, zone_id: str) -> list[dict[str, Any]]:
    listed = _api_get(token, f"/zones/{zone_id}/rulesets")
    if not isinstance(listed, list):
        raise CloudflareStateError("Cloudflare rulesets list response is not a list")

    rulesets: list[dict[str, Any]] = []
    for item in listed:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind", "")) != "zone":
            continue
        if str(item.get("phase", "")) not in RULESET_DETAIL_PHASES:
            continue
        ruleset_id = item.get("id")
        if not ruleset_id:
            continue
        detail = _api_get(token, f"/zones/{zone_id}/rulesets/{ruleset_id}")
        if isinstance(detail, dict):
            rulesets.append(detail)
    return rulesets


def _collect_access_apps(token: str, zone_id: str) -> list[dict[str, Any]]:
    result = _api_get(token, f"/zones/{zone_id}/access/apps")
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def _collect_live_headers(base_url: str | None) -> dict[str, str]:
    if not base_url:
        return {}
    url = f"{base_url.rstrip('/')}/api/v1/health"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https":
        raise CloudflareStateError(f"refusing non-HTTPS live probe URL: {url}")
    request = urllib.request.Request(url)  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return dict(response.headers)


def build_state_from_cloudflare(
    *,
    token: str,
    zone_id: str,
    base_url: str | None,
    policy: dict[str, Any],
) -> dict[str, Any]:
    access_apps = _collect_access_apps(token, zone_id)
    rulesets = _collect_rulesets(token, zone_id)
    headers = _collect_live_headers(base_url)
    return build_state_from_payloads(
        policy=policy,
        access_apps=access_apps,
        rulesets=rulesets,
        live_response_headers=headers,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build CLOUDFLARE_STATE_JSON for News Sentry deployed-surface audit."
    )
    parser.add_argument("--policy", default="config/security/deployment-surface-policy.yaml")
    parser.add_argument(
        "--zone-id",
        default=os.getenv("CLOUDFLARE_ZONE_ID") or os.getenv("CF_ZONE_ID"),
    )
    parser.add_argument("--base-url", default="https://news-sentry.com")
    parser.add_argument("--output", required=True)
    parser.add_argument("--api-token")
    parser.add_argument("--no-wrangler", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    if not args.zone_id:
        raise SystemExit("missing --zone-id or CLOUDFLARE_ZONE_ID/CF_ZONE_ID")

    policy = load_policy(args.policy)
    try:
        token = _resolve_api_token(args)
        state = build_state_from_cloudflare(
            token=token,
            zone_id=args.zone_id,
            base_url=args.base_url,
            policy=policy,
        )
    except CloudflareStateError as exc:
        print(f"Cloudflare state collection failed: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    findings = build_cloudflare_state_findings(state, policy)
    print(
        json.dumps(
            {
                "output": str(output),
                "finding_count": len(findings),
                "finding_classes": [item["finding_class"] for item in findings],
            },
            ensure_ascii=False,
        )
    )
    return 1 if findings and not args.allow_partial else 0


if __name__ == "__main__":
    raise SystemExit(main())
