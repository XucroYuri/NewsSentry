"""P23.02 — OWASP Top 10 Quick Security Audit for News Sentry v1.0."""

from __future__ import annotations

import re
from pathlib import Path

src = Path("src/news_sentry")
issues: list[str] = []

for f in src.rglob("*.py"):
    text = f.read_text(encoding="utf-8", errors="replace")
    lines = text.split("\n")
    rel = str(f.relative_to(src.parent.parent))

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # A02 - Hardcoded secrets
        if re.search(
            r"(password|secret|token|api_key|apikey)\s*=\s*['\"][^'\"]+['\"]",
            stripped,
            re.I,
        ):
            if "os.environ" not in line and "config" not in line.lower():
                if stripped.startswith("#") or "test" in str(f):
                    continue
                issues.append(f"A02:{rel}:{i}: Possible hardcoded secret")

        # A03 - Injection in subprocess
        if "subprocess.run" in line and ("shell=True" in line or ".format(" in line):
            issues.append(f"A03:{rel}:{i}: Potential injection in subprocess")

        # A05 - Debug mode
        if "debug=True" in line and "test" not in str(f):
            issues.append(f"A05:{rel}:{i}: Debug mode enabled")

        # A09 - Sensitive data in logs
        if re.search(r"log\.(info|debug|warning|error)", line, re.I):
            if re.search(r"(password|token|secret|api_key)", line, re.I):
                issues.append(f"A09:{rel}:{i}: Possible sensitive data in log")

if issues:
    for issue in issues:
        print(f"WARNING  {issue}")
else:
    print("PASS  OWASP Top 10 quick scan: no high-severity findings")

py_count = len(list(src.rglob("*.py")))
print(f"Scanned: {py_count} Python files")
