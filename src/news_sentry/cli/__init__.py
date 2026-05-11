"""CLI entry point — python -m news_sentry.cli run --target <id> --stage <stage>."""
from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml


@click.group()
@click.version_option()
def main() -> None:
    """News Sentry — continuous news monitoring Agent Skill Pack."""


@main.command()
@click.option(
    "--target", required=True,
    help="Target ID (e.g., italy). Maps to config/targets/{id}.yaml",
)
@click.option(
    "--stage",
    required=True,
    type=click.Choice(["collect", "filter", "judge", "output", "all"]),
    help="Pipeline stage to execute.",
)
@click.option("--run-id", default=None, help="Specify run_id. Auto-generated if not provided.")
@click.option("--dry-run", is_flag=True, default=False, help="Print plan without executing.")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING"]))
@click.option("--config-dir", default=None, help="Override project root directory.")
@click.option(
    "--profile",
    "profile_id",
    default=None,
    help="Deployment profile ID. Overrides NEWSSENTRY_PROFILE.",
)
def run(target: str, stage: str, run_id: str | None, dry_run: bool,
        log_level: str, config_dir: str | None, profile_id: str | None) -> None:
    """Execute a bounded run for a monitoring target.

    Exit codes: 0=success, 1=partial failure, 2=config error, 3=sandbox blocked.
    """
    from news_sentry.core.run import ConfigError, bounded_run

    try:
        ctx = bounded_run(
            target_id=target,
            stage=stage,
            run_id=run_id,
            dry_run=dry_run,
            config_dir=config_dir,
            profile_id=profile_id,
        )
        if dry_run:
            click.echo(f"target: {ctx.target_id}")
            click.echo(f"run_id: {ctx.run_id}")
            click.echo(f"stage:  {stage}")
            click.echo(f"profile: {ctx.profile_id}")
            click.echo("dry-run: 不执行实际操作")
        elif ctx.errors_count > 0:
            click.echo(
                f"⚠ {ctx.errors_count} 个源采集失败，详见 RunLog: {ctx.run_log_path}"
            )
            sys.exit(1)
    except ConfigError as e:
        click.echo(f"配置错误: {e}", err=True)
        sys.exit(2)
    except Exception as e:
        click.echo(f"运行异常: {e}", err=True)
        sys.exit(1)


@main.command("skill")
@click.argument("action", type=click.Choice(["list"]))
def skill_cmd(action: str) -> None:
    """Manage skills — list available skills from src/news_sentry/skills/."""
    skills_dir = _find_project_root(Path(__file__)) / "src" / "news_sentry" / "skills"
    if not skills_dir.is_dir():
        click.echo("Skills directory not found.")
        return

    entries: list[dict[str, str]] = []
    for child in sorted(skills_dir.iterdir()):
        if child.is_dir() and not child.name.startswith("_") and not child.name.startswith("."):
            init_file = child / "__init__.py"
            if init_file.is_file():
                doc = _extract_module_doc(init_file)
                entries.append({"name": child.name, "description": doc})
    if not entries:
        click.echo("No skills found.")
        return
    for entry in entries:
        click.echo(f"  {entry['name']:<25}  {entry['description']}")


@main.command("tool")
@click.argument("action", type=click.Choice(["list"]))
def tool_cmd(action: str) -> None:
    """Manage tools — list available tools from config/toolmanifest/."""
    toolmanifest_dir = _find_project_root(Path(__file__)) / "config" / "toolmanifest"
    if not toolmanifest_dir.is_dir():
        click.echo("Tool manifest directory not found.")
        return

    entries: list[dict[str, str]] = []
    for child in sorted(toolmanifest_dir.glob("*.yaml")):
        try:
            with open(child, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            tools = data.get("tools", []) if isinstance(data, dict) else []
            for tool in tools:
                if isinstance(tool, dict):
                    entries.append({
                        "tool_id": tool.get("tool_id", "?"),
                        "display_name": tool.get("display_name", ""),
                        "version": tool.get("version", ""),
                    })
        except Exception:  # noqa: S112
            continue
    if not entries:
        click.echo("No tools found.")
        return
    for entry in entries:
        click.echo(
            f"  {entry['tool_id']:<30} {entry['version']:<8} {entry['display_name']}"
        )


@main.command()
@click.option("--config", required=True, help="Path to YAML config file to validate.")
def validate(config: str) -> None:
    """Validate a YAML config file and its declared JSON Schema when present."""
    from news_sentry.core.config import ConfigLoader

    config_path = Path(config).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path

    try:
        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if data is not None and not isinstance(data, dict):
            raise click.ClickException("YAML root must be a mapping/object.")

        loader = ConfigLoader(_find_project_root(config_path))
        loader._validate_resolved_schema(data or {}, config_path)
    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(str(e)) from e

    click.echo(f"valid: {config_path}")


@main.command()
@click.option("--json", "as_json", is_flag=True, default=False, help="Output as JSON")
@click.option("--target", default="italy", help="监控目标 ID")
@click.option("--data-root", default="data", help="数据根目录")
def doctor(as_json: bool, target: str, data_root: str) -> None:
    """运行项目健康检查 — schema/目录/信源/Provider。"""
    from news_sentry.cli.doctor import run_doctor as run_target_doctor

    results = _run_doctor_checks()

    # 集成目标级健康检查
    try:
        target_report = run_target_doctor(target, data_root)
        for check_name, check in target_report.to_dict().items():
            if check_name == "overall":
                continue
            passed = bool(check.get("passed"))
            details = check.get("details", [])
            results.append({
                "name": f"Target: {check_name}",
                "ok": passed,
                "severity": "critical" if (not passed and check_name == "schema_check") else ("warning" if not passed else "info"),
                "message": "; ".join(details) if details else ("ok" if passed else "fail"),
            })
    except Exception as e:
        results.append({
            "name": "Target health check",
            "ok": False,
            "severity": "warning",
            "message": str(e),
        })

    if as_json:
        import json as _json

        click.echo(_json.dumps(results, indent=2, ensure_ascii=False))
    else:
        _print_doctor_results(results)

    has_critical_failure = any(
        not r["ok"] and r.get("severity") == "critical" for r in results
    )
    if has_critical_failure:
        sys.exit(1)


def _run_doctor_checks() -> list[dict[str, object]]:
    """Run all health checks and return structured results."""
    results: list[dict[str, object]] = []

    # 1. Python version
    py_version = sys.version_info
    py_ok = py_version >= (3, 11)
    results.append({
        "name": "Python version",
        "ok": py_ok,
        "severity": "critical",
        "message": f"{py_version.major}.{py_version.minor}.{py_version.micro}"
        if py_ok else f"{py_version.major}.{py_version.minor} (< 3.11)",
    })

    # 2. Core dependency imports
    core_packages = {
        "pydantic": "pydantic",
        "yaml (pyyaml)": "yaml",
        "httpx": "httpx",
        "feedparser": "feedparser",
        "click": "click",
    }
    for display_name, import_name in core_packages.items():
        try:
            __import__(import_name)
            results.append({
                "name": f"Import {display_name}",
                "ok": True,
                "severity": "critical",
                "message": "ok",
            })
        except ImportError:
            results.append({
                "name": f"Import {display_name}",
                "ok": False,
                "severity": "critical",
                "message": "not found",
            })

    # 3. Project import
    try:
        from news_sentry.cli import main as _main  # noqa: F401
        results.append({
            "name": "Project import",
            "ok": True,
            "severity": "critical",
            "message": "ok",
        })
    except ImportError as e:
        results.append({
            "name": "Project import",
            "ok": False,
            "severity": "critical",
            "message": str(e),
        })

    # 4. Config loading (best effort)
    project_root = _find_project_root(Path(__file__))
    try:
        from news_sentry.core.config import ConfigLoader
        ConfigLoader(project_root)
        results.append({
            "name": "Config loading",
            "ok": True,
            "severity": "info",
            "message": f"ConfigLoader initialized from {project_root}",
        })
    except Exception as e:
        results.append({
            "name": "Config loading",
            "ok": False,
            "severity": "warning",
            "message": str(e),
        })

    # 5. Data directory permissions
    data_dir = project_root / "data"
    if data_dir.is_dir():
        results.append({
            "name": "Data directory",
            "ok": True,
            "severity": "critical",
            "message": str(data_dir),
        })
    else:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            results.append({
                "name": "Data directory",
                "ok": True,
                "severity": "critical",
                "message": f"created: {data_dir}",
            })
        except OSError as e:
            results.append({
                "name": "Data directory",
                "ok": False,
                "severity": "critical",
                "message": str(e),
            })

    # 6. Optional: opencli in PATH
    from shutil import which
    opencli_path = which("opencli")
    results.append({
        "name": "opencli (optional)",
        "ok": True,
        "severity": "info",
        "message": opencli_path if opencli_path else "not found",
    })

    # 7. Optional: git repo
    git_dir = project_root / ".git"
    results.append({
        "name": "Git repository (optional)",
        "ok": True,
        "severity": "info",
        "message": "found" if git_dir.is_dir() else "not a git repo",
    })

    # 8. Adapter health — skills and tools
    try:
        from news_sentry.core.adapter_health import check_all_adapters
        from news_sentry.core.skill_registry import SkillRegistry
        from news_sentry.core.tool_registry import ToolRegistry

        skills_dir_path = project_root / "src" / "news_sentry" / "skills"
        tool_dir_path = project_root / "config" / "toolmanifest"
        tr = ToolRegistry(tool_dir_path)
        sr = SkillRegistry(skills_dir_path)
        adapter_results = check_all_adapters(tr, sr)
        results.extend(adapter_results)
    except Exception as e:
        results.append({
            "name": "Adapter health",
            "ok": False,
            "severity": "warning",
            "message": str(e),
        })

    return results


def _print_doctor_results(results: list[dict[str, object]]) -> None:
    """Pretty-print doctor check results to stdout."""
    severity_icons = {"critical": "[!]", "warning": "[~]", "info": "[i]"}
    for r in results:
        icon = severity_icons.get(str(r.get("severity", "info")), "[ ]")
        status = "OK " if r["ok"] else "FAIL"
        click.echo(f"  {icon} {status}  {r['name']}: {r['message']}")


def _find_project_root(path: Path) -> Path:
    """Find the nearest project root for schema resolution."""
    for parent in [path.parent, *path.parent.parents]:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()


def _extract_module_doc(filepath: Path) -> str:
    """Extract the first line of a Python module's docstring, or empty string."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return ""
    # 简单的三引号 docstring 提取
    import ast
    try:
        tree = ast.parse(text)
        doc = ast.get_docstring(tree)
        if doc:
            return doc.strip().split("\n")[0]
    except SyntaxError:
        pass
    return ""


__all__ = ["main"]
