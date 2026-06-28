#!/usr/bin/env python3
"""Audit deployed public surfaces against the deployment surface policy."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from deployment_surface_security import (
    build_cloudflare_state_findings,
    build_surface_findings,
    load_policy,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def base_url_for_surface(surface: str, public_base_url: str, api_base_url: str | None) -> str:
    if surface.startswith("/api/") and api_base_url:
        return api_base_url
    return public_base_url


def _probe_surface(
    base_url: str,
    surface: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}{surface}"
    with httpx.Client(follow_redirects=False, timeout=timeout_seconds) as client:
        response = client.get(url)
    return {
        "surface": surface,
        "status_code": response.status_code,
        "headers": dict(response.headers),
    }


def _collect_live_probes(
    policy: dict[str, Any],
    base_url: str,
    api_base_url: str | None,
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    rules = policy["surface_rules"]["default_probe_surfaces"]
    probes: list[dict[str, Any]] = []
    for surface in [*rules["public"], *rules["protected"], *rules["architecture"]]:
        surface_base_url = base_url_for_surface(surface, base_url, api_base_url)
        probes.append(_probe_surface(surface_base_url, surface, timeout_seconds))
    return probes


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit deployed public surfaces.")
    parser.add_argument("--policy", required=True, help="Path to deployment surface policy YAML.")
    parser.add_argument("--output", required=True, help="Where to write the JSON audit report.")
    parser.add_argument("--probes-json", help="Existing probe JSON array to audit.")
    parser.add_argument("--cloudflare-state-json", help="Optional Cloudflare state JSON.")
    parser.add_argument("--base-url", help="Live base URL to probe when probes-json is absent.")
    parser.add_argument(
        "--api-base-url",
        help="Optional API origin for split Cloudflare Pages + Worker deployments.",
    )
    parser.add_argument(
        "--environment",
        default="production",
        help="Label for the audited environment.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    args = parser.parse_args()

    policy = load_policy(args.policy)
    if args.probes_json:
        probes = _load_json(Path(args.probes_json))
    elif args.base_url:
        probes = _collect_live_probes(
            policy,
            args.base_url,
            args.api_base_url,
            args.timeout_seconds,
        )
    else:
        raise SystemExit("either --probes-json or --base-url is required")

    cloudflare_state = (
        _load_json(Path(args.cloudflare_state_json))
        if args.cloudflare_state_json
        else None
    )

    findings = build_surface_findings(list(probes), policy)
    findings.extend(build_cloudflare_state_findings(cloudflare_state, policy))
    report = {
        "policy_id": policy["policy_id"],
        "environment": args.environment,
        "generated_at": datetime.now(UTC).isoformat(),
        "finding_count": len(findings),
        "findings": findings,
    }
    _write_json(Path(args.output), report)
    print(
        json.dumps(
            {
                "policy_id": report["policy_id"],
                "environment": report["environment"],
                "finding_count": report["finding_count"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
