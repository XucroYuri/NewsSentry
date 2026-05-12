"""News Sentry — CLI doctor: 项目健康检查."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel

REQUIRED_DIRS = [
    "raw", "evaluated", "drafts", "reviewed", "published",
    "archive", "memory", "logs",
]

REQUIRED_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
]


class DoctorReport(BaseModel):
    schema_check: dict[str, Any] = {}
    directory_check: dict[str, Any] = {}
    source_check: dict[str, Any] = {}
    provider_check: dict[str, Any] = {}
    browser_bridge_check: dict[str, Any] = {}
    session_profiles_check: dict[str, Any] = {}

    @property
    def all_passed(self) -> bool:
        checks = [
            self.schema_check,
            self.directory_check,
            self.source_check,
            self.provider_check,
            self.browser_bridge_check,
            self.session_profiles_check,
        ]
        return all(c.get("passed", False) for c in checks if c)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_check": self.schema_check,
            "directory_check": self.directory_check,
            "source_check": self.source_check,
            "provider_check": self.provider_check,
            "browser_bridge_check": self.browser_bridge_check,
            "session_profiles_check": self.session_profiles_check,
            "overall": "PASS" if self.all_passed else "FAIL",
        }


def run_doctor(target_id: str, data_root: str = "data") -> DoctorReport:
    data_path = Path(data_root) / target_id

    # Schema check
    schema_ok = True
    schema_details: list[str] = []
    schemas_dir = Path("schemas")
    if schemas_dir.is_dir():
        schema_count = len(list(schemas_dir.glob("*.json")))
        schema_details.append(f"{schema_count} schema files found")
    else:
        schema_ok = False
        schema_details.append("schemas/ directory missing")

    # Directory check
    dir_ok = True
    dir_details: list[str] = []
    for d in REQUIRED_DIRS:
        p = data_path / d
        if p.is_dir():
            dir_details.append(f"{d}/ exists")
        else:
            dir_ok = False
            dir_details.append(f"{d}/ MISSING")

    # Source check — placeholder (network required)
    source_ok = True
    source_details = ["source reachability check requires network (skip in CI)"]

    # Provider check
    provider_ok = True
    provider_details: list[str] = []
    for var in REQUIRED_ENV_VARS:
        if os.environ.get(var):
            provider_details.append(f"{var} is set")
        else:
            provider_ok = False
            provider_details.append(f"{var} not set")

    # Browser Bridge check
    bridge_ok = True
    bridge_details: list[str] = []

    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    chromedriver = shutil.which("chromedriver")
    xdpyinfo = shutil.which("xdpyinfo")

    if chromium:
        bridge_details.append(f"Chromium found at {chromium}")
    else:
        bridge_details.append("Chromium not found")
    if chromedriver:
        bridge_details.append(f"ChromeDriver found at {chromedriver}")
    else:
        bridge_details.append("ChromeDriver not found")

    # Xvfb display check
    display_ok = False
    if xdpyinfo:
        try:
            result = subprocess.run(
                ["xdpyinfo", "-display", ":99"],  # noqa: S607 — xdpyinfo path varies by distro
                capture_output=True, text=True, timeout=5,
            )
            display_ok = result.returncode == 0
        except Exception:  # noqa: S110 — Xvfb may not be running, health check handles this
            pass
    bridge_details.append(f"Xvfb display :99 {'available' if display_ok else 'not running'}")

    # OpenCLI check
    opencli = shutil.which("opencli")
    opencli_ok = False
    if opencli:
        try:
            result = subprocess.run(  # noqa: S603 — opencli path from shutil.which, trusted input
                [opencli, "--version"], capture_output=True, text=True, timeout=10,
            )
            opencli_ok = result.returncode == 0
        except Exception:  # noqa: S110 — opencli may not be installed, health check handles this
            pass
    bridge_details.append(f"OpenCLI {'available' if opencli_ok else 'not found'}")

    # Playwright check
    npx = shutil.which("npx")
    playwright_ok = False
    if npx:
        try:
            result = subprocess.run(  # noqa: S603 — npx path from shutil.which, trusted input
                [npx, "playwright", "--version"], capture_output=True, text=True, timeout=10,
            )
            playwright_ok = result.returncode == 0
        except Exception:  # noqa: S110 — playwright may not be installed, health check handles this
            pass
    bridge_details.append(f"Playwright {'available' if playwright_ok else 'not available'}")

    bridge_ok = bool(chromium) and bool(chromedriver)

    # Session Profiles check
    session_ok = True
    session_details: list[str] = []
    session_dir = Path("config/session-profiles/italy")
    if not session_dir.exists():
        session_ok = False
        session_details.append("config/session-profiles/italy/ not found")
    else:
        yaml_files = list(session_dir.glob("*.yaml"))
        session_files = list(session_dir.glob("*.session.*"))
        session_details.append(
            f"{len(yaml_files)} session configs, {len(session_files)} session files"
        )

    return DoctorReport(
        schema_check={"passed": schema_ok, "details": schema_details},
        directory_check={"passed": dir_ok, "details": dir_details},
        source_check={"passed": source_ok, "details": source_details},
        provider_check={"passed": provider_ok, "details": provider_details},
        browser_bridge_check={"passed": bridge_ok, "details": bridge_details},
        session_profiles_check={"passed": session_ok, "details": session_details},
    )


def doctor_command(target: str, data_root: str = "data", json_output: bool = False) -> int:
    report = run_doctor(target, data_root)
    if json_output:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        status = "PASS" if report.all_passed else "FAIL"
        print(f"Doctor check: {status}")
        for check_name, check in report.to_dict().items():
            if check_name == "overall":
                continue
            icon = "PASS" if check.get("passed") else "FAIL"
            print(f"  [{icon}] {check_name}")
            for detail in check.get("details", []):
                print(f"     {detail}")
    return 0 if report.all_passed else 1
