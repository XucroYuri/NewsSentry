"""INV-D 的又一实例：**测试必须走真实入口**。

背景：L1.3–L1.6 的三个工具在首版中缺少 `sys.path` bootstrap
（`from tools.control_common import ...` 在直接运行脚本时无法解析），
因此**作为命令行完全不可用**；而 35 项单元测试全部通过 ——
因为它们直接导入并调用 `main()`，pytest 已把仓库根放进 `sys.path`。

**"可导入的函数"与"可执行的命令行"是两个不同的制品。**
本文件通过 subprocess 调用真实命令，并刻意把 cwd 设在工作区外的临时目录。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "c" * 40
TOOLS = ("control_receipt", "control_compare", "isolation_proof")


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - 运行的是仓库自有的工具脚本，非外部输入
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("tool", TOOLS)
def test_tool_runs_as_a_script_outside_the_repo(tool: str, tmp_path: Path) -> None:
    """从仓库外的目录调用真实脚本 —— 这正是 sys.path bootstrap 的作用。"""
    result = _run(str(ROOT / "tools" / f"{tool}.py"), "--help", cwd=tmp_path)

    assert result.returncode == 0, f"{tool} 无法作为脚本运行：{result.stderr}"
    assert "usage" in result.stdout.lower()


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(json.dumps([{"results": rows}]), encoding="utf-8")


def test_receipt_and_compare_run_end_to_end(tmp_path: Path) -> None:
    """完整链路：build 回执 → validate → compare，全部经真实命令行。"""
    rows = [
        {"event_id": "ne-a-1-20260919-aaaaaaaa", "value_score": 70.0, "pipeline_stage": "judged"},
        {"event_id": "ne-a-2-20260919-bbbbbbbb", "value_score": 40.0, "pipeline_stage": "judged"},
    ]
    control = tmp_path / "control.json"
    treatment = tmp_path / "treatment.json"
    _write_rows(control, rows)
    _write_rows(treatment, rows)

    receipt = tmp_path / "receipt.json"
    build = _run(
        str(ROOT / "tools" / "control_receipt.py"),
        "build",
        "--track", "control",
        "--environment", "production",
        "--run-id", "cli-e2e",
        "--commit", COMMIT,
        "--events", str(control),
        "--window-start", "2026-09-19T00:00:00Z",
        "--window-end", "2026-09-20T00:00:00Z",
        "--cpu-p50", "1.0",
        "--cpu-p99", "4.0",
        "--cpu-samples", "10",
        "--source-ok-ratio", "0.95",
        "--output", str(receipt),
        cwd=tmp_path,
    )
    assert build.returncode == 0, build.stderr

    validate = _run(
        str(ROOT / "tools" / "control_receipt.py"),
        "validate",
        "--input", str(receipt),
        cwd=tmp_path,
    )
    assert validate.returncode == 0, validate.stderr

    dominance = tmp_path / "dominance.json"
    compare = _run(
        str(ROOT / "tools" / "control_compare.py"),
        "compare",
        "--control-events", str(control),
        "--treatment-events", str(treatment),
        "--output", str(dominance),
        cwd=tmp_path,
    )
    assert compare.returncode == 0, compare.stderr

    report = json.loads(dominance.read_text(encoding="utf-8"))
    assert report["event_sets"]["recall"] == 1.0
    # 缺数据 ⇒ 不支配（fail-closed）
    assert report["verdict"] == "not_dominant"
    assert any("缺少 A/B 双方数据" in blocker for blocker in report["blockers"])


def test_compare_assert_dominance_exit_code(tmp_path: Path) -> None:
    rows = [{"event_id": "ne-a-1-20260919-aaaaaaaa", "value_score": 70.0}]
    control = tmp_path / "c.json"
    treatment = tmp_path / "t.json"
    _write_rows(control, rows)
    _write_rows(treatment, rows)

    result = _run(
        str(ROOT / "tools" / "control_compare.py"),
        "compare",
        "--control-events", str(control),
        "--treatment-events", str(treatment),
        "--assert-dominance",
        cwd=tmp_path,
    )

    assert result.returncode == 1
    assert "未达支配" in result.stderr


def test_isolation_verify_runs_end_to_end(tmp_path: Path) -> None:
    sentinel = "iso-sentinel-preview-clitest"
    control = tmp_path / "c.json"
    treatment = tmp_path / "t.json"
    _write_rows(control, [{"event_id": "ne-a-1-20260919-aaaaaaaa"}])
    _write_rows(treatment, [{"event_id": "ne-a-1-20260919-aaaaaaaa"}, {"event_id": sentinel}])

    passed = _run(
        str(ROOT / "tools" / "isolation_proof.py"),
        "verify",
        "--sentinel", sentinel,
        "--written-to", "treatment",
        "--control-events", str(control),
        "--treatment-events", str(treatment),
        cwd=tmp_path,
    )
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "PASS" in passed.stdout

    _write_rows(control, [{"event_id": sentinel}])  # 泄漏
    leaked = _run(
        str(ROOT / "tools" / "isolation_proof.py"),
        "verify",
        "--sentinel", sentinel,
        "--written-to", "treatment",
        "--control-events", str(control),
        "--treatment-events", str(treatment),
        cwd=tmp_path,
    )
    assert leaked.returncode == 1
    assert "FAIL" in leaked.stdout
