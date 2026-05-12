"""RunLog 模块测试。

覆盖：RunLog 初始化、write、阶段日志、错误记录、write_heartbeat。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from news_sentry.core.run_log import RunLog, write_heartbeat

# ── RunLog 初始化 ───────────────────────────────────────────────────────


class TestInit:
    """RunLog.__init__ 测试。"""

    def test_default_fields(self, tmp_path: Path):
        """基本字段正确赋值。"""
        log = RunLog(
            log_dir=tmp_path,
            run_id="italy_20260510T103000Z_a1b2c3d4",
        )
        assert log.run_id == "italy_20260510T103000Z_a1b2c3d4"
        assert log.target_id == "italy"
        assert log.profile_id == "local-workstation"
        assert "T" in log.started_at
        assert log._written is False

    def test_explicit_target_id(self, tmp_path: Path):
        """显式传入 target_id 覆盖 run_id 推断。"""
        log = RunLog(
            log_dir=tmp_path,
            run_id="some-random-id",
            target_id="eu_china",
        )
        assert log.target_id == "eu_china"

    def test_parse_target_id_with_underscore(self, tmp_path: Path):
        """包含下划线的 target_id（如 eu_china）正确解析。"""
        log = RunLog(
            log_dir=tmp_path,
            run_id="eu_china_20260510T103000Z_a1b2c3d4",
        )
        assert log.target_id == "eu_china"

    def test_parse_target_id_short_format(self, tmp_path: Path):
        """简短测试格式 run_id 正确解析。"""
        log = RunLog(
            log_dir=tmp_path,
            run_id="italy_20260510T103000",
        )
        assert log.target_id == "italy"


# ── RunLog 阶段日志 ────────────────────────────────────────────────────


class TestPhaseLogging:
    """阶段日志记录测试。"""

    def test_log_phase_start_and_end(self, tmp_path: Path):
        """log_phase_start 和 log_phase_end 正确记录。"""
        log = RunLog(log_dir=tmp_path, run_id="test_run", target_id="italy")

        log.log_phase_start("collect")
        log.log_phase_end("collect", items_count=5, duration_ms=1200.5)

        phase = log._phases["collect"]
        assert phase["stage"] == "collect"
        assert phase["started_at"] is not None
        assert phase["ended_at"] is not None
        assert phase["items_count"] == 5
        assert phase["duration_ms"] == 1200.5

    def test_log_event(self, tmp_path: Path):
        """log_event 记录处理动作。"""
        log = RunLog(log_dir=tmp_path, run_id="test_run", target_id="italy")

        log.log_phase_start("filter")
        log.log_event("filter", "evt-001", "filtered_in")
        log.log_event("filter", "evt-002", "filtered_out")

        phase = log._phases["filter"]
        assert len(phase["_events"]) == 2
        assert phase["_events"][0] == {"event_id": "evt-001", "action": "filtered_in"}

    def test_log_error(self, tmp_path: Path):
        """log_error 记录错误。"""
        log = RunLog(log_dir=tmp_path, run_id="test_run", target_id="italy")

        log.log_phase_start("collect")
        log.log_error("collect", "Connection refused", event_id="evt-err")

        assert log.errors_count == 1
        phase = log._phases["collect"]
        assert len(phase["errors"]) == 1
        assert phase["errors"][0]["message"] == "Connection refused"
        assert phase["errors"][0]["event_id"] == "evt-err"

    def test_log_error_multiple_phases(self, tmp_path: Path):
        """多阶段错误计数。"""
        log = RunLog(log_dir=tmp_path, run_id="test_run", target_id="italy")

        log.log_phase_start("collect")
        log.log_error("collect", "err1")
        log.log_phase_start("filter")
        log.log_error("filter", "err2")
        log.log_error("filter", "err3")

        assert log.errors_count == 3


# ── RunLog write ────────────────────────────────────────────────────────


class TestWrite:
    """RunLog.write 测试。"""

    def test_write_creates_log_file(self, tmp_path: Path):
        """write 创建 logs/{run_id}.json 文件。"""
        log = RunLog(log_dir=tmp_path, run_id="test_write", target_id="italy")

        log.log_phase_start("collect")
        log.log_phase_end("collect", items_count=3, duration_ms=500.0)
        log.log_phase_start("filter")
        log.log_phase_end("filter", items_count=2, duration_ms=300.0)

        output_path = log.write()
        assert output_path.exists()
        assert output_path.name == "test_write.json"

    def test_write_content_structure(self, tmp_path: Path):
        """write 输出的 JSON 结构完整。"""
        log = RunLog(log_dir=tmp_path, run_id="test_struct", target_id="italy")

        log.log_phase_start("collect")
        log.log_phase_end("collect", items_count=10, duration_ms=800.0)
        log.log_error("collect", "Some error", event_id="evt-1")

        output_path = log.write()
        content = json.loads(output_path.read_text(encoding="utf-8"))

        assert content["run_id"] == "test_struct"
        assert content["target_id"] == "italy"
        assert content["profile_id"] == "local-workstation"
        assert "started_at" in content
        assert "ended_at" in content
        assert len(content["phases"]) == 1
        assert content["phases"][0]["stage"] == "collect"
        assert content["phases"][0]["items_count"] == 10
        assert content["phases"][0]["duration_ms"] == 800.0
        assert content["errors_count"] == 1
        assert len(content["errors"]) == 1

    def test_write_idempotent(self, tmp_path: Path):
        """多次 write 调用幂等，返回相同路径。"""
        log = RunLog(log_dir=tmp_path, run_id="test_idempotent", target_id="italy")

        log.log_phase_start("collect")
        log.log_phase_end("collect", items_count=1, duration_ms=100.0)

        path1 = log.write()
        path2 = log.write()
        assert path1 == path2

    def test_write_summary(self, tmp_path: Path):
        """write 输出包含正确 summary。"""
        log = RunLog(log_dir=tmp_path, run_id="test_summary", target_id="italy")

        log.log_phase_start("collect")
        log.log_phase_end("collect", items_count=5, duration_ms=100.0)
        log.log_phase_start("filter")
        log.log_phase_end("filter", items_count=3, duration_ms=50.0)

        output_path = log.write()
        content = json.loads(output_path.read_text(encoding="utf-8"))
        summary = content["summary"]
        assert summary["total_events_collected"] == 5
        assert summary["total_events_filtered_in"] == 3


# ── write_heartbeat ─────────────────────────────────────────────────────


class TestWriteHeartbeat:
    """write_heartbeat 函数测试。"""

    def test_write_heartbeat_creates_file(self, tmp_path: Path):
        """write_heartbeat 创建 .heartbeat-hermes.json 文件。"""
        heartbeat_path = write_heartbeat(
            log_dir=tmp_path,
            run_id="test-run-001",
            stage="collect",
            status="running",
        )

        assert heartbeat_path.exists()
        assert heartbeat_path.name == ".heartbeat-hermes.json"

        content = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        assert content["run_id"] == "test-run-001"
        assert content["last_stage"] == "collect"
        assert content["status"] == "running"
        assert "last_at" in content
        assert "T" in content["last_at"]

    def test_write_heartbeat_atomic(self, tmp_path: Path):
        """.tmp 文件不残留，验证原子写入。"""
        write_heartbeat(
            log_dir=tmp_path,
            run_id="test-run-002",
            stage="judge",
            status="completed",
        )

        # 确认 .tmp 文件不存在
        tmp_file = tmp_path / ".heartbeat-hermes.json.tmp"
        assert not tmp_file.exists(), f".tmp 文件不应残留: {tmp_file}"

        # 确认目标文件存在
        heartbeat_file = tmp_path / ".heartbeat-hermes.json"
        assert heartbeat_file.exists()

    def test_write_heartbeat_overwrites(self, tmp_path: Path):
        """多次调用 heartbeat，文件被覆盖（最新状态）。"""
        write_heartbeat(tmp_path, "run-001", "collect", "running")
        write_heartbeat(tmp_path, "run-001", "filter", "running")
        write_heartbeat(tmp_path, "run-001", "judge", "completed")

        content = json.loads((tmp_path / ".heartbeat-hermes.json").read_text(encoding="utf-8"))
        assert content["last_stage"] == "judge"
        assert content["status"] == "completed"


# ── JsonLogFormatter ─────────────────────────────────────────────────────


def test_json_formatter_includes_required_fields():
    from news_sentry.core.run_log import JsonLogFormatter

    fmt = JsonLogFormatter(run_id="r-001", target_id="italy", stage="collect")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=1,
        msg="test message",
        args=(),
        exc_info=None,
    )
    output = fmt.format(record)
    data = json.loads(output)

    assert data["run_id"] == "r-001"
    assert data["target_id"] == "italy"
    assert data["stage"] == "collect"
    assert data["message"] == "test message"
    assert data["level"] == "INFO"
    assert "timestamp" in data
