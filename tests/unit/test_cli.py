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
        json.dumps({
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }),
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
