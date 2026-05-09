"""Implements: docs/spec/phase-3-kernel-mvp.md §3.1, ADR-0016

CLI entry point: news-sentry run --target <target_id> --stage <stage>
"""
from __future__ import annotations
import sys
import click
from news_sentry.models.newsevent import PipelineStage


@click.group()
@click.version_option()
def main() -> None:
    """News Sentry — continuous news monitoring Agent Skill Pack."""


@main.command()
@click.option("--target", required=True, help="Target ID (e.g., italy). Maps to config/targets/{id}.yaml")
@click.option(
    "--stage",
    required=True,
    type=click.Choice(["collect", "filter", "judge", "output", "all"]),
    help="Pipeline stage to execute.",
)
@click.option("--run-id", default=None, help="Specify run_id (UUID4). Auto-generated if not provided.")
@click.option("--dry-run", is_flag=True, default=False, help="Print plan without executing.")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING"]))
@click.option("--config-dir", default=None, help="Override default config/ directory path.")
def run(target: str, stage: str, run_id: str | None, dry_run: bool,
        log_level: str, config_dir: str | None) -> None:
    """Execute a bounded run for a monitoring target.

    Exit codes: 0=success, 1=partial failure, 2=config error, 3=sandbox blocked.
    """
    raise NotImplementedError("Phase 3: CLI run command — calls core.run.bounded_run")


@main.command("skill")
@click.argument("action", type=click.Choice(["list"]))
def skill_cmd(action: str) -> None:
    """Manage skills."""
    raise NotImplementedError("Phase 4: skill list command")


@main.command("tool")
@click.argument("action", type=click.Choice(["list"]))
def tool_cmd(action: str) -> None:
    """Manage tools."""
    raise NotImplementedError("Phase 4: tool list command")


@main.command()
@click.option("--config", required=True, help="Path to YAML config file to validate.")
def validate(config: str) -> None:
    """Validate a config YAML file against its JSON Schema."""
    raise NotImplementedError("Phase 3: validate command — calls ConfigLoader._validate_against_schema")


if __name__ == "__main__":
    main()
