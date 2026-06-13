from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools" / "seo_geo"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(TOOLS_DIR))

from update_rule_sources import (  # noqa: E402
    build_rule_sources_report,
    describe_registry_ref,
    load_rule_sources,
)
from verify_public_site import (  # noqa: E402
    ResourceSnapshot,
    build_homepage_checks,
    build_sitemap_checks,
    extract_head_snapshot,
    summarize_checks,
)


def test_extract_head_snapshot_reads_meta_canonical_and_json_ld() -> None:
    html = """
    <!doctype html>
    <html lang="zh-CN">
      <head>
        <title>News Sentry Public</title>
        <meta name="description" content="Public discoverability surface." />
        <meta property="og:title" content="News Sentry Public" />
        <link rel="canonical" href="https://news-sentry.com/public-app/" />
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"CollectionPage","name":"News Sentry Public"}
        </script>
      </head>
      <body></body>
    </html>
    """

    snapshot = extract_head_snapshot(html)

    assert snapshot["title"] == "News Sentry Public"
    assert snapshot["meta_name"]["description"] == "Public discoverability surface."
    assert snapshot["meta_property"]["og:title"] == "News Sentry Public"
    assert snapshot["links"]["canonical"] == "https://news-sentry.com/public-app/"
    assert snapshot["json_ld"][0]["@type"] == "CollectionPage"


def test_build_homepage_checks_flags_missing_canonical_and_json_ld() -> None:
    page = ResourceSnapshot(
        path="/public-app",
        url="https://news-sentry.com/public-app",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        text="""
        <!doctype html>
        <html>
          <head>
            <title>News Sentry Public</title>
            <meta name="description" content="Public discoverability surface." />
            <meta property="og:title" content="News Sentry Public" />
          </head>
          <body></body>
        </html>
        """,
    )

    checks = build_homepage_checks(page, base_url="https://news-sentry.com")
    check_map = {check["name"]: check for check in checks}

    assert check_map["homepage_status_ok"]["ok"] is True
    assert check_map["homepage_meta_description_present"]["ok"] is True
    assert check_map["homepage_canonical_matches_expected"]["ok"] is False
    assert check_map["homepage_json_ld_present"]["ok"] is False


def test_summarize_checks_counts_failures_and_exposes_failed_names() -> None:
    report = summarize_checks(
        base_url="https://news-sentry.com",
        checks=[
            {"name": "robots_status_ok", "ok": True, "severity": "error", "detail": "200"},
            {"name": "homepage_status_ok", "ok": True, "severity": "error", "detail": "200"},
            {
                "name": "homepage_canonical_matches_expected",
                "ok": False,
                "severity": "error",
                "detail": "missing canonical",
            },
            {
                "name": "homepage_json_ld_present",
                "ok": False,
                "severity": "error",
                "detail": "no application/ld+json blocks",
            },
        ],
    )

    assert report["schema_version"] == 1
    assert report["ok"] is False
    assert report["counts"] == {"total": 4, "passed": 2, "failed": 2}
    assert report["failed_checks"] == [
        "homepage_canonical_matches_expected",
        "homepage_json_ld_present",
    ]


def test_build_sitemap_checks_fails_origin_check_when_sitemap_is_empty_or_404() -> None:
    snapshot = ResourceSnapshot(
        path="/sitemap.xml",
        url="https://news-sentry.com/sitemap.xml",
        status_code=404,
        headers={"content-type": "application/json"},
        text="",
    )

    checks = build_sitemap_checks(snapshot, base_url="https://news-sentry.com")
    check_map = {check["name"]: check for check in checks}

    assert check_map["sitemap_status_ok"]["ok"] is False
    assert check_map["sitemap_parses_as_urlset"]["ok"] is False
    assert check_map["sitemap_urls_match_site_origin"]["ok"] is False


def test_build_rule_sources_report_uses_stable_registry_value() -> None:
    registry = load_rule_sources(PROJECT_ROOT / "tools" / "seo_geo" / "rule_sources.json")

    report = build_rule_sources_report(registry, categories={"official"})

    assert report["registry"] == "tools/seo_geo/rule_sources.json"
    assert "registry_path" not in report


def test_build_rule_sources_report_reflects_non_default_registry_reference(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "custom-rule-sources.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "custom": [
                    {
                        "id": "custom-source",
                        "type": "official",
                        "url": "https://example.com/custom",
                        "topics": ["custom"],
                        "enabled": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_rule_sources_report(
        load_rule_sources(registry_path),
        categories={"custom"},
        registry_ref="custom-rule-sources.json",
    )

    assert report["registry"] == "custom-rule-sources.json"


def test_describe_registry_ref_is_stable_across_callers_cwd(tmp_path: Path) -> None:
    registry_path = tmp_path / "custom-rule-sources.json"
    registry_path.write_text('{"schema_version": 1, "custom": []}', encoding="utf-8")
    nested_cwd = tmp_path / "nested" / "caller"
    nested_cwd.mkdir(parents=True)

    from_parent_cwd = describe_registry_ref(registry_path, cwd=tmp_path)
    from_nested_cwd = describe_registry_ref(registry_path, cwd=nested_cwd)

    assert from_parent_cwd == from_nested_cwd


def test_update_rule_sources_cli_rejects_unknown_category() -> None:
    result = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "tools/seo_geo/update_rule_sources.py",
            "--category",
            "typo-category",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_categories"
    assert payload["error"]["unknown_categories"] == ["typo-category"]
