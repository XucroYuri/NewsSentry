"""Phase 50 — serve 命令单元测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn  # noqa: F401 — 确保 uvicorn 可被 patch("uvicorn.run") 解析
from click.testing import CliRunner

from news_sentry.cli import main
from news_sentry.cli.serve import _load_env_file, _pid_alive

# ------------------------------------------------------------------
# _load_env_file
# ------------------------------------------------------------------


class TestLoadEnvFile:
    """_load_env_file() 单元测试。"""

    def test_parses_key_value_lines(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        monkeypatch.delenv("NEWSSENTRY_PORT", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("NEWSSENTRY_DATA_DIR=/opt/data\nNEWSSENTRY_PORT=9000\n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_DATA_DIR"] == "/opt/data"
        assert os.environ["NEWSSENTRY_PORT"] == "9000"

    def test_skips_comment_lines(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("# this is a comment\nNEWSSENTRY_DATA_DIR=/opt/data\n")
        _load_env_file(env_file)
        assert "NEWSSENTRY_DATA_DIR" in os.environ
        assert "# this is a comment" not in str(os.environ)

    def test_skips_lines_without_equals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("NOT_A_VALID_LINE\nNEWSSENTRY_DATA_DIR=/opt/data\n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_DATA_DIR"] == "/opt/data"
        assert "NOT_A_VALID_LINE" not in os.environ

    def test_does_not_override_existing_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        os.environ["NEWSSENTRY_EXISTING"] = "original_value"
        env_file = tmp_path / ".env"
        env_file.write_text("NEWSSENTRY_EXISTING=new_value\nNEWSSENTRY_DATA_DIR=/opt/data\n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_EXISTING"] == "original_value"
        assert os.environ["NEWSSENTRY_DATA_DIR"] == "/opt/data"

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("")
        _load_env_file(env_file)

    def test_handles_nonexistent_file(self, tmp_path: Path) -> None:
        _load_env_file(tmp_path / "nonexistent_env_file")

    def test_handles_blank_lines(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        monkeypatch.delenv("NEWSSENTRY_PORT", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("\n\nNEWSSENTRY_DATA_DIR=/opt/data\n\n\nNEWSSENTRY_PORT=9000\n\n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_DATA_DIR"] == "/opt/data"
        assert os.environ["NEWSSENTRY_PORT"] == "9000"

    def test_strips_whitespace_around_values(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("NEWSSENTRY_DATA_DIR", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("  NEWSSENTRY_DATA_DIR = /opt/data  \n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_DATA_DIR"] == "/opt/data"

    def test_env_file_integration_sets_multiple_vars(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """集成测试：临时 env 文件正确设置多个环境变量。"""
        monkeypatch.delenv("NEWSSENTRY_INTEG_A", raising=False)
        monkeypatch.delenv("NEWSSENTRY_INTEG_B", raising=False)
        monkeypatch.delenv("NEWSSENTRY_INTEG_C", raising=False)
        env_file = tmp_path / "test.env"
        env_file.write_text(
            "NEWSSENTRY_INTEG_A=/custom/data\nNEWSSENTRY_INTEG_B=italy\nNEWSSENTRY_INTEG_C=30\n"
        )
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_INTEG_A"] == "/custom/data"
        assert os.environ["NEWSSENTRY_INTEG_B"] == "italy"
        assert os.environ["NEWSSENTRY_INTEG_C"] == "30"


class TestLoadEnvFileEdgeCases:
    """_load_env_file() 边界情况。"""

    def test_line_with_only_equals_sign(self, tmp_path: Path) -> None:
        """只有等号没有 key 的行应被跳过。"""
        env_file = tmp_path / ".env"
        env_file.write_text("=\n")
        _load_env_file(env_file)

    def test_line_with_multiple_equals(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """值中包含等号应正确解析（只用第一个等号分割）。"""
        monkeypatch.delenv("NEWSSENTRY_BASE64", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("NEWSSENTRY_BASE64=dGhpcyBpcyBhIHRlc3Q=\n")
        _load_env_file(env_file)
        assert os.environ["NEWSSENTRY_BASE64"] == "dGhpcyBpcyBhIHRlc3Q="

    def test_value_only_no_key(self, tmp_path: Path) -> None:
        """=value 格式：key 为空，应跳过。"""
        env_file = tmp_path / ".env"
        env_file.write_text("=value_only\n")
        _load_env_file(env_file)
        assert "=value_only" not in str(os.environ)


# ------------------------------------------------------------------
# _pid_alive
# ------------------------------------------------------------------


class TestPidAlive:
    """_pid_alive() 单元测试。"""

    def test_returns_false_for_nonexistent_file(self, tmp_path: Path) -> None:
        assert _pid_alive(tmp_path / "nonexistent_pid_file") is False

    def test_returns_false_for_non_numeric_content(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("not-a-pid")
        assert _pid_alive(pid_file) is False

    def test_returns_false_for_empty_pid_file(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("")
        assert _pid_alive(pid_file) is False

    def test_returns_true_when_kill_succeeds(self, tmp_path: Path) -> None:
        """Unix: os.kill(pid, 0) 成功表示进程存活。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific kill test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")
        with patch("os.kill", return_value=None):
            assert _pid_alive(pid_file) is True

    def test_returns_false_when_kill_raises_oserror(self, tmp_path: Path) -> None:
        """Unix: os.kill(pid, 0) 抛出 OSError 表示进程不存在。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific kill test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")
        with patch("os.kill", side_effect=OSError):
            assert _pid_alive(pid_file) is False


# ------------------------------------------------------------------
# serve 命令注册
# ------------------------------------------------------------------


class TestServeCommandRegistration:
    """serve 子命令注册检查。"""

    def test_serve_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "serve" in cmd_names

    def test_serve_help_contains_expected_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        for opt in ("--host", "--port", "--target", "--interval", "--data-dir", "--no-browser"):
            assert opt in result.output

    def test_serve_help_mentions_api_server(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "API" in result.output


# ------------------------------------------------------------------
# serve 命令行为（mock uvicorn）
# ------------------------------------------------------------------


def _setup_serve_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """为 serve 命令测试设置通用 mock。"""
    monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
    monkeypatch.setattr(os, "getpid", lambda: 12345)
    monkeypatch.setattr("webbrowser.open", lambda _url: None)


class TestServeCommandBehavior:
    """serve 命令运行行为测试（mock uvicorn 避免实际启动服务器）。"""

    def test_serve_exits_with_error_when_already_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """已有 PID 文件且进程存活时应报错退出。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("99999")
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: True)
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "serve",
                "--data-dir",
                str(tmp_path / "data"),
                "--log-dir",
                str(tmp_path / "logs"),
                "--pid-file",
                str(pid_file),
                "--no-browser",
                "--foreground",
            ],
        )
        assert result.exit_code == 1
        assert "already running" in result.output

    def test_serve_starts_uvicorn_when_not_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """无进程冲突时应启动 uvicorn。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        with patch("uvicorn.run") as mock_uvicorn:
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--pid-file",
                    str(pid_file),
                    "--no-browser",
                    "--foreground",
                ],
            )

        mock_uvicorn.assert_called_once()
        assert result.exit_code == 0

    def test_serve_creates_data_and_log_dirs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """serve 应自动创建 data 和 log 目录。"""
        data_dir = tmp_path / "custom_data"
        log_dir = tmp_path / "custom_logs"
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        with patch("uvicorn.run"):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(data_dir),
                    "--log-dir",
                    str(log_dir),
                    "--pid-file",
                    str(pid_file),
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert data_dir.is_dir()
        assert log_dir.is_dir()

    def test_serve_sets_env_vars_before_uvicorn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """serve 应在启动 uvicorn 前设置环境变量。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        captured_env: dict[str, str] = {}

        def fake_uvicorn_run(*args, **kwargs):  # noqa: ARG001
            captured_env["data_dir"] = os.environ.get("NEWSSENTRY_DATA_DIR", "")
            captured_env["auto_collect"] = os.environ.get("NEWSSENTRY_AUTO_COLLECT", "")
            captured_env["target_id"] = os.environ.get("NEWSSENTRY_TARGET_ID", "")

        with patch("uvicorn.run", side_effect=fake_uvicorn_run):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--pid-file",
                    str(pid_file),
                    "--target",
                    "italy,japan",
                    "--interval",
                    "10",
                    "--profile",
                    "cloud-vps",
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert captured_env["auto_collect"] == "1"
        assert captured_env["target_id"] == "italy,japan"
        assert str(tmp_path / "data") in captured_env["data_dir"]

    def test_serve_writes_pid_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """serve 应将当前 PID 写入 PID 文件。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        with patch("uvicorn.run"):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--pid-file",
                    str(pid_file),
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert pid_file.is_file()
        assert pid_file.read_text().strip() == "12345"

    def test_serve_no_browser_skips_open(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-browser 标志应跳过浏览器打开。"""
        pid_file = tmp_path / "serve.pid"

        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(os, "getpid", lambda: 12345)

        browser_called: list[bool] = []

        def fake_webbrowser_open(_url: str) -> None:
            browser_called.append(True)

        monkeypatch.setattr("webbrowser.open", fake_webbrowser_open)

        with patch("uvicorn.run"):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--pid-file",
                    str(pid_file),
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert len(browser_called) == 0

    def test_serve_help_shows_all_options(self) -> None:
        """serve --help 显示所有预期选项。"""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        expected_options = [
            "--host",
            "--port",
            "--target",
            "--interval",
            "--profile",
            "--data-dir",
            "--log-dir",
            "--pid-file",
            "--no-browser",
            "--foreground",
        ]
        for opt in expected_options:
            assert opt in result.output, f"Expected option {opt} not found in help output"

    def test_serve_with_target_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """未指定 --target 时默认值为 all。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        captured_target: dict[str, str] = {}

        def fake_uvicorn_run(*args, **kwargs):  # noqa: ARG001
            captured_target["target"] = os.environ.get("NEWSSENTRY_TARGET_ID", "")

        with patch("uvicorn.run", side_effect=fake_uvicorn_run):
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--pid-file",
                    str(pid_file),
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert captured_target["target"] == "all"
