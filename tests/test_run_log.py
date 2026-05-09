"""测试 core/run_log.py — RunLog 审计日志记录与序列化"""
from __future__ import annotations

import json
from pathlib import Path

from news_sentry.core.run_log import RunLog


def test_full_collect_filter_output_flow(tmp_path: Path) -> None:
    """测试完整的 collect -> filter -> output 流程记录"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="italy_20240115T103000")

    # collect 阶段
    log.log_phase_start("collect")
    log.log_event("collect", "ne-italy-ansa-20240115-abc00001", "collected")
    log.log_event("collect", "ne-italy-repubblica-20240115-def00002", "collected")
    log.log_event("collect", "ne-italy-corriere-20240115-ghi00003", "collected")
    log.log_phase_end("collect", items_count=3, duration_ms=45000.5)

    # filter 阶段
    log.log_phase_start("filter")
    log.log_event("filter", "ne-italy-ansa-20240115-abc00001", "filtered_in")
    log.log_event("filter", "ne-italy-repubblica-20240115-def00002", "filtered_in")
    log.log_event("filter", "ne-italy-corriere-20240115-ghi00003", "filtered_out")
    log.log_phase_end("filter", items_count=3, duration_ms=5000.0)

    # output 阶段
    log.log_phase_start("output")
    log.log_event("output", "ne-italy-ansa-20240115-abc00001", "outputted")
    log.log_event("output", "ne-italy-repubblica-20240115-def00002", "outputted")
    log.log_phase_end("output", items_count=2, duration_ms=1200.0)

    path = log.write()

    # 文件存在且内容可解析
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["run_id"] == "italy_20240115T103000"
    assert data["target_id"] == "italy"
    assert "started_at" in data
    assert "ended_at" in data
    assert len(data["phases"]) == 3

    # 验证 summary
    summary = data["summary"]
    assert summary["total_events_collected"] == 3
    assert summary["total_events_filtered_in"] == 2
    assert summary["total_events_filtered_out"] == 1
    assert summary["total_errors"] == 0


def test_write_output_is_valid_json(tmp_path: Path) -> None:
    """测试写入文件内容可被 json.load 正确解析"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="italy_20240115T103000")
    log.log_phase_start("collect")
    log.log_phase_end("collect", items_count=10, duration_ms=3000.0)
    path = log.write()

    # 用 json.load 验证文件是合法 JSON
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert data["run_id"] == "italy_20240115T103000"
    assert len(data["phases"]) == 1
    assert data["phases"][0]["stage"] == "collect"
    assert data["phases"][0]["items_count"] == 10
    assert data["phases"][0]["duration_ms"] == 3000.0


def test_log_error_records_error_info(tmp_path: Path) -> None:
    """测试 log_error 正确记录错误信息"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="italy_20240115T103000")
    log.log_phase_start("collect")
    log.log_error("collect", "Connection timeout", event_id="ne-italy-ansa-20240115-abc00001")
    log.log_error("collect", "Rate limit exceeded")
    log.log_phase_end("collect", items_count=0, duration_ms=10000.0)
    path = log.write()

    data = json.loads(path.read_text(encoding="utf-8"))
    errors = data["phases"][0]["errors"]
    assert len(errors) == 2
    assert errors[0]["message"] == "Connection timeout"
    assert errors[0]["event_id"] == "ne-italy-ansa-20240115-abc00001"
    assert errors[1]["message"] == "Rate limit exceeded"
    assert "event_id" not in errors[1]

    assert data["summary"]["total_errors"] == 2


def test_run_id_in_filename(tmp_path: Path) -> None:
    """测试 run_id 写入文件名正确"""
    log_dir = tmp_path / "logs"
    run_id = "italy_20240115T103000"
    log = RunLog(log_dir=log_dir, run_id=run_id)
    log.log_phase_start("collect")
    log.log_phase_end("collect", items_count=0, duration_ms=0.0)
    path = log.write()

    assert path.name == f"{run_id}.json"
    assert path.parent == log_dir


def test_write_is_idempotent(tmp_path: Path) -> None:
    """测试 write() 多次调用幂等，只写第一次"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="italy_20240115T103000")
    log.log_phase_start("collect")
    log.log_phase_end("collect", items_count=5, duration_ms=1000.0)

    path1 = log.write()
    path2 = log.write()
    path3 = log.write()

    assert path1 == path2 == path3


def test_target_id_from_run_id_with_hyphens(tmp_path: Path) -> None:
    """测试包含连字符的 target_id（如 eu-china）能从 run_id 正确解析"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="eu-china_20240115T103000")
    log.log_phase_start("collect")
    log.log_phase_end("collect", items_count=1, duration_ms=500.0)
    path = log.write()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["target_id"] == "eu-china"
    assert data["run_id"] == "eu-china_20240115T103000"


def test_phase_without_explicit_start(tmp_path: Path) -> None:
    """测试未调用 log_phase_start 直接记录事件时不会崩溃"""
    log_dir = tmp_path / "logs"
    log = RunLog(log_dir=log_dir, run_id="italy_20240115T103000")
    # 不调用 log_phase_start，直接记事件
    log.log_event("collect", "ne-italy-ansa-20240115-abc00001", "collected")
    log.log_phase_end("collect", items_count=1, duration_ms=100.0)
    path = log.write()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["phases"][0]["started_at"] is None
