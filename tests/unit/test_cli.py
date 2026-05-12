"""CLI behavior tests."""

from __future__ import annotations

import json

from click.testing import CliRunner

from news_sentry.cli import main
from news_sentry.models.newsevent import PipelineStage
from news_sentry.models.pipeline_context import PipelineContext


def _ctx(errors_count: int = 0) -> PipelineContext:
    return PipelineContext(
        run_id="run-test",
        target_id="italy",
        stage=PipelineStage.COLLECTED,
        started_at="2026-05-09T00:00:00+00:00",
        profile_id="local-workstation",
        errors_count=errors_count,
    )


def test_run_passes_profile_to_bounded_run(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_bounded_run(**kwargs):
        captured["profile_id"] = kwargs["profile_id"]
        return _ctx()

    monkeypatch.setattr("news_sentry.core.run.bounded_run", fake_bounded_run)

    result = CliRunner().invoke(
        main,
        ["run", "--target", "italy", "--stage", "collect", "--profile", "cloud-vps"],
    )

    assert result.exit_code == 0
    assert captured["profile_id"] == "cloud-vps"


def test_run_returns_one_when_context_has_errors(monkeypatch):
    def fake_bounded_run(**_kwargs):
        return _ctx(errors_count=2)

    monkeypatch.setattr("news_sentry.core.run.bounded_run", fake_bounded_run)

    result = CliRunner().invoke(
        main,
        ["run", "--target", "italy", "--stage", "collect"],
    )

    assert result.exit_code == 1


def test_dry_run_prints_profile(monkeypatch):
    def fake_bounded_run(**_kwargs):
        return _ctx()

    monkeypatch.setattr("news_sentry.core.run.bounded_run", fake_bounded_run)

    result = CliRunner().invoke(
        main,
        ["run", "--target", "italy", "--stage", "collect", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "profile: local-workstation" in result.output


def test_validate_accepts_portable_automation_yaml(tmp_path):
    config_path = tmp_path / "news-sentry-test.yaml"
    config_path.write_text(
        """
name: "News Sentry - Italy Monitor Test"
command: "python -m news_sentry.cli run --target italy --stage collect --profile local-workstation"
working_dir: "${project_root}"
expected_exit_codes: [0, 1]
output_validation:
  type: latest_run_log
  path: "data/italy/logs/"
  pattern: "*.json"
""".strip(),
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["validate", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "valid:" in result.output


def test_validate_uses_declared_schema(tmp_path):
    schema_path = tmp_path / "example.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "example.yaml"
    config_path.write_text(
        "# Schema: example.schema.json\nname: ok\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["validate", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "valid:" in result.output


# ------------------------------------------------------------------
# skill list
# ------------------------------------------------------------------


def test_skill_list_outputs_skill_names():
    """skill list 应输出 collect、filter、judge、output 等核心技能名称。"""
    result = CliRunner().invoke(main, ["skill", "list"])
    assert result.exit_code == 0
    for name in ("collect", "filter", "judge", "output"):
        assert name in result.output


def test_skill_list_no_error():
    """skill list 应以 exit_code 0 退出。"""
    result = CliRunner().invoke(main, ["skill", "list"])
    assert result.exit_code == 0


# ------------------------------------------------------------------
# tool list
# ------------------------------------------------------------------


def test_tool_list_outputs_tool_ids():
    """tool list 应输出 config/toolmanifest/ 中定义的工具 ID。"""
    result = CliRunner().invoke(main, ["tool", "list"])
    assert result.exit_code == 0
    # opencli-baseline.yaml 中定义的 12 条工具
    for tool_id in ("opencli.fetch", "opencli.search", "opencli.extract"):
        assert tool_id in result.output


# ------------------------------------------------------------------
# doctor
# ------------------------------------------------------------------


def test_doctor_exits_zero():
    """doctor 命令应正常退出。"""
    result = CliRunner().invoke(main, ["doctor"])
    assert result.exit_code == 0


def test_doctor_reports_python_version():
    """doctor 输出应包含 Python 版本信息。"""
    result = CliRunner().invoke(main, ["doctor"])
    assert "Python" in result.output


def test_doctor_json_flag():
    """doctor --json 应输出有效 JSON。"""
    result = CliRunner().invoke(main, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) > 0


# ------------------------------------------------------------------
# validate
# ------------------------------------------------------------------


def test_validate_rejects_invalid_yaml(tmp_path):
    """validate 对不符合 schema 的 YAML 应报错。"""
    schema_path = tmp_path / "test.schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        "# Schema: test.schema.json\nother_field: 123\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["validate", "--config", str(config_path)])
    assert result.exit_code != 0


# ------------------------------------------------------------------
# --version / --help
# ------------------------------------------------------------------


def test_version_flag():
    """--version 应输出版本号并正常退出。"""
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "version" in result.output.lower() or "." in result.output


def test_help_flag():
    """--help 应列出可用命令。"""
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("run", "doctor", "validate", "skill", "tool"):
        assert cmd in result.output


def test_run_help():
    """run --help 应显示选项。"""
    result = CliRunner().invoke(main, ["run", "--help"])
    assert result.exit_code == 0
    assert "--target" in result.output
    assert "--stage" in result.output
    assert "--profile" in result.output
