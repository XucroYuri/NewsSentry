"""Phase 50 — serve 命令单元测试。"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import time
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
        for opt in (
            "--host",
            "--port",
            "--target",
            "--interval",
            "--stage",
            "--log-level",
            "--data-dir",
            "--no-browser",
        ):
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
            captured_env["collect_stage"] = os.environ.get("NEWSSENTRY_COLLECT_STAGE", "")
            captured_env["collect_interval"] = os.environ.get("NEWSSENTRY_COLLECT_INTERVAL", "")

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
                    "--stage",
                    "all",
                    "--profile",
                    "cloud-vps",
                    "--no-browser",
                    "--foreground",
                ],
            )
        assert result.exit_code == 0
        assert captured_env["auto_collect"] == "1"
        assert captured_env["target_id"] == "italy,japan"
        assert captured_env["collect_stage"] == "all"
        assert captured_env["collect_interval"] == "10"
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
            "--stage",
            "--log-level",
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
        """未指定 --target/--stage 时默认值分别为 all 和 all。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        captured: dict[str, str] = {}

        def fake_uvicorn_run(*args, **kwargs):  # noqa: ARG001
            captured["target"] = os.environ.get("NEWSSENTRY_TARGET_ID", "")
            captured["stage"] = os.environ.get("NEWSSENTRY_COLLECT_STAGE", "")

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
        assert captured["target"] == "all"
        assert captured["stage"] == "all"

    def test_serve_rejects_invalid_stage(self) -> None:
        """--stage 不接受无效值。"""
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--stage", "invalid"])
        assert result.exit_code != 0

    def test_serve_exits_with_error_when_uvicorn_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """uvicorn 未安装时应给出友好错误提示。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        # 模拟 uvicorn 未安装
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "uvicorn":
                raise ImportError("No module named 'uvicorn'")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fake_import):
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
        assert "uvicorn" in result.output

    def test_serve_accepts_valid_stage_values(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--stage 接受所有有效阶段值。"""
        pid_file = tmp_path / "serve.pid"
        _setup_serve_mocks(monkeypatch)

        for stage in ("collect", "filter", "judge", "output", "all"):
            captured: dict[str, str] = {}

            def make_fake_uvicorn(cap: dict[str, str]) -> object:
                def fake_uvicorn_run(*args: object, **kwargs: object) -> None:
                    cap["stage"] = os.environ.get("NEWSSENTRY_COLLECT_STAGE", "")

                return fake_uvicorn_run

            with patch("uvicorn.run", side_effect=make_fake_uvicorn(captured)):
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
                        "--stage",
                        stage,
                        "--no-browser",
                        "--foreground",
                    ],
                )
            assert result.exit_code == 0, f"--stage {stage} should be accepted"
            assert captured["stage"] == stage


# ------------------------------------------------------------------
# stop 命令
# ------------------------------------------------------------------


class TestStopCommand:
    """news-sentry stop 命令测试。"""

    def test_stop_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "stop" in cmd_names

    def test_stop_no_pid_file(self, tmp_path: Path) -> None:
        """PID 文件不存在时正常退出，无报错。"""
        nonexistent = tmp_path / "nonexistent.pid"
        runner = CliRunner()
        result = runner.invoke(main, ["stop", "--pid-file", str(nonexistent)])
        assert result.exit_code == 0
        assert "No PID file found" in result.output

    def test_stop_stale_pid(self, tmp_path: Path) -> None:
        """PID 文件存在但进程已不存在时应清理 PID 文件。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")
        # _pid_alive 会返回 False（文件内容不匹配真实进程）
        runner = CliRunner()
        result = runner.invoke(main, ["stop", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        assert "not alive" in result.output
        assert not pid_file.is_file()  # stale PID file removed

    def test_stop_invalid_pid_content(self, tmp_path: Path) -> None:
        """PID 文件内容非法时应清理并正常退出。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("not-a-pid")
        runner = CliRunner()
        result = runner.invoke(main, ["stop", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        assert not pid_file.is_file()

    def test_stop_sends_signal(self, tmp_path: Path) -> None:
        """Unix: 进程存活的 PID 文件应触发 kill + 清理。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific signal test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")
        with patch("news_sentry.cli.serve._pid_alive", return_value=True):
            with patch("os.kill") as mock_kill:
                runner = CliRunner()
                result = runner.invoke(main, ["stop", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)
        assert not pid_file.is_file()

    def test_stop_handles_kill_failure(self, tmp_path: Path) -> None:
        """kill 调用失败时应报错退出。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific signal test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")
        with patch("news_sentry.cli.serve._pid_alive", return_value=True):
            with patch("os.kill", side_effect=OSError("Permission denied")):
                runner = CliRunner()
                result = runner.invoke(main, ["stop", "--pid-file", str(pid_file)])
        assert result.exit_code == 1
        assert "Failed to send signal" in result.output


# ------------------------------------------------------------------
# install 命令
# ------------------------------------------------------------------


class TestInstallCommand:
    """news-sentry install 命令测试。"""

    def test_install_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "install" in cmd_names

    def test_install_help_shows_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["install", "--help"])
        assert result.exit_code == 0
        for opt in ("--target", "--interval", "--stage", "--force", "--port"):
            assert opt in result.output

    def test_install_macos_writes_plist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """macOS 上 install 生成 LaunchAgent plist。"""
        if sys.platform == "win32":
            pytest.skip("macOS-specific test")
        plist_dir = tmp_path / "LaunchAgents"
        plist_dir.mkdir(parents=True)
        fake_home = tmp_path

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        # Prevent actual launchctl invocation.
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(fake_home / ".news-sentry/data"),
                "--log-dir",
                str(fake_home / ".news-sentry/logs"),
                "--pid-file",
                str(fake_home / ".news-sentry/serve.pid"),
                "--force",
            ],
            catch_exceptions=False,
        )
        # Note: plist goes to Path.home()/Library/LaunchAgents, so in test it's tmp_path/Library/...
        expected_plist = fake_home / "Library/LaunchAgents/com.news-sentry.plist"
        assert expected_plist.is_file(), f"Expected plist at {expected_plist}"
        content = expected_plist.read_text()
        assert "com.news-sentry" in content
        assert "LaunchAgent" not in content.lower()  # it's the proper plist DOCTYPE
        assert result.exit_code == 0

    def test_install_macos_rejects_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """macOS 上 plist 已存在且未 --force 时应报错。"""
        if sys.platform == "win32":
            pytest.skip("macOS-specific test")
        fake_home = tmp_path
        plist_dir = fake_home / "Library/LaunchAgents"
        plist_dir.mkdir(parents=True)
        plist_dir.joinpath("com.news-sentry.plist").write_text("existing")

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(fake_home / ".news-sentry/data"),
                "--log-dir",
                str(fake_home / ".news-sentry/logs"),
            ],
        )
        assert result.exit_code == 1
        assert "already installed" in result.output

    def test_install_linux_writes_systemd_unit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Linux 上 install 生成 systemd user unit。"""
        fake_home = tmp_path

        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(fake_home / ".news-sentry/data"),
                "--log-dir",
                str(fake_home / ".news-sentry/logs"),
                "--pid-file",
                str(fake_home / ".news-sentry/serve.pid"),
                "--force",
            ],
        )
        expected_unit = fake_home / ".config/systemd/user/news-sentry.service"
        assert expected_unit.is_file(), f"Expected unit at {expected_unit}"
        content = expected_unit.read_text()
        assert "[Unit]" in content
        assert "[Service]" in content
        assert "[Install]" in content
        assert "ExecStart=" in content
        assert "news-sentry" in content
        assert result.exit_code == 0

    def test_install_linux_rejects_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Linux 上 unit 文件已存在且未 --force 时应报错。"""
        fake_home = tmp_path
        unit_dir = fake_home / ".config/systemd/user"
        unit_dir.mkdir(parents=True)
        unit_dir.joinpath("news-sentry.service").write_text("existing")

        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(fake_home / ".news-sentry/data"),
                "--log-dir",
                str(fake_home / ".news-sentry/logs"),
            ],
        )
        assert result.exit_code == 1
        assert "already installed" in result.output

    def test_install_unsupported_os(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """不支持的 OS 应报错退出。"""
        monkeypatch.setattr(platform, "system", lambda: "FreeBSD")
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(tmp_path / "data"),
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        )
        assert result.exit_code == 1
        assert "Unsupported OS" in result.output

    def test_install_passes_serve_options_to_plist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """install --target/--interval/--stage 应写入 plist。"""
        if sys.platform == "win32":
            pytest.skip("macOS-specific test")
        fake_home = tmp_path
        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "install",
                "--data-dir",
                str(fake_home / ".news-sentry/data"),
                "--log-dir",
                str(fake_home / ".news-sentry/logs"),
                "--target",
                "italy",
                "--interval",
                "10",
                "--stage",
                "judge",
                "--port",
                "9000",
                "--log-level",
                "debug",
                "--force",
            ],
        )
        assert result.exit_code == 0
        plist = fake_home / "Library/LaunchAgents/com.news-sentry.plist"
        content = plist.read_text()
        assert "italy" in content
        assert "10" in content
        assert "judge" in content
        assert "9000" in content
        assert "debug" in content


# ------------------------------------------------------------------
# status 命令
# ------------------------------------------------------------------


class TestStatusCommand:
    """news-sentry status 命令测试。"""

    def test_status_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "status" in cmd_names

    def test_status_shows_stopped_when_no_pid_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--pid-file", str(tmp_path / "nonexistent.pid")])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()

    def test_status_shows_running_when_pid_alive(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PID 文件存在且进程存活时显示 running。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")

        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: True)

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        assert "running" in result.output.lower()
        assert "12345" in result.output

    def test_status_json_output(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--json 输出机器可读格式。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")

        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: True)

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--pid-file", str(pid_file), "--json"])
        assert result.exit_code == 0
        assert '"running": true' in result.output
        assert '"pid": 12345' in result.output

    def test_status_json_stopped(self, tmp_path: Path) -> None:
        """--json 输出 stopped 状态。"""
        runner = CliRunner()
        result = runner.invoke(
            main, ["status", "--pid-file", str(tmp_path / "nonexistent.pid"), "--json"]
        )
        assert result.exit_code == 0
        assert '"running": false' in result.output

    def test_status_stale_pid(self, tmp_path: Path) -> None:
        """PID 文件存在但进程已死时显示 stopped。"""
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("99999")
        # _pid_alive defaults to False for non-numeric in test, but 99999 is numeric,
        # and no real process has that PID in test, so it'll be correctly False.
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--pid-file", str(pid_file)])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()


# ------------------------------------------------------------------
# logs 命令
# ------------------------------------------------------------------


class TestLogsCommand:
    """news-sentry logs 命令测试。"""

    def test_logs_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "logs" in cmd_names

    def test_logs_shows_last_lines(self, tmp_path: Path) -> None:
        """logs 默认显示最后 N 行。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "serve.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(1, 101)))

        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--log-dir", str(log_dir), "--lines", "10"])
        assert result.exit_code == 0
        assert "line 91" in result.output
        assert "line 100" in result.output
        # Early lines should not appear.
        assert "line 1\n" not in result.output

    def test_logs_file_not_found(self, tmp_path: Path) -> None:
        """日志文件不存在时应报错。"""
        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--log-dir", str(tmp_path / "nonexistent")])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_logs_default_lines_50(self, tmp_path: Path) -> None:
        """默认显示 50 行。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "serve.log"
        log_file.write_text("\n".join(f"line {i}" for i in range(1, 61)))

        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--log-dir", str(log_dir)])
        assert result.exit_code == 0
        # 60 lines total, default 50 — first line "line 1" should not appear.
        assert "line 1" not in result.output.splitlines()
        assert "line 60" in result.output

    def test_logs_follow_flag_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--follow/-f 参数应被接受（通过模拟 KeyboardInterrupt 退出）。"""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "serve.log"
        log_file.write_text("single line\n")

        # Replace time.sleep to raise KeyboardInterrupt, simulating Ctrl+C in follow mode.
        def fake_sleep(seconds: float) -> None:  # noqa: ARG001
            raise KeyboardInterrupt()

        monkeypatch.setattr(time, "sleep", fake_sleep)

        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--log-dir", str(log_dir), "--follow"])
        # Should exit cleanly after catching KeyboardInterrupt.
        assert result.exit_code == 0


# ------------------------------------------------------------------
# restart 命令
# ------------------------------------------------------------------


class TestRestartCommand:
    """news-sentry restart 命令测试。"""

    def test_restart_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "restart" in cmd_names

    def test_restart_help_shows_serve_options(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["restart", "--help"])
        assert result.exit_code == 0
        for opt in ("--target", "--interval", "--stage", "--port", "--log-level"):
            assert opt in result.output

    def test_restart_when_not_running_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """服务未运行时 restart 直接启动。"""
        pid_file = tmp_path / "serve.pid"

        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(time, "sleep", lambda _s: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "restart",
                "--pid-file",
                str(pid_file),
                "--data-dir",
                str(tmp_path / "data"),
                "--log-dir",
                str(tmp_path / "logs"),
                "--no-browser",
            ],
        )
        assert result.exit_code == 0

    def test_restart_kills_running_process(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """运行中的服务应被 kill 再重启。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific signal test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")

        alive_count = [0]

        def pid_alive(path):
            alive_count[0] += 1
            return alive_count[0] <= 1  # First call=True, then False

        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", pid_alive)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: None)
        monkeypatch.setattr(time, "sleep", lambda _s: None)

        with patch("os.kill") as mock_kill:
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "restart",
                    "--pid-file",
                    str(pid_file),
                    "--data-dir",
                    str(tmp_path / "data"),
                    "--log-dir",
                    str(tmp_path / "logs"),
                    "--no-browser",
                ],
            )
        assert result.exit_code == 0
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)


# ------------------------------------------------------------------
# uninstall 命令
# ------------------------------------------------------------------


class TestUninstallCommand:
    """news-sentry uninstall 命令测试。"""

    def test_uninstall_appears_in_main_commands(self) -> None:
        cmd_names = list(main.commands.keys())
        assert "uninstall" in cmd_names

    def test_uninstall_macos_removes_plist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """macOS 上 uninstall 删除 plist 并 unload。"""
        fake_home = tmp_path
        plist_dir = fake_home / "Library/LaunchAgents"
        plist_dir.mkdir(parents=True)
        plist_path = plist_dir / "com.news-sentry.plist"
        plist_path.write_text("fake plist")

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "uninstall",
                "--pid-file",
                str(tmp_path / "serve.pid"),
            ],
        )
        assert result.exit_code == 0
        assert not plist_path.is_file()
        assert "Uninstall complete" in result.output

    def test_uninstall_linux_removes_unit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Linux 上 uninstall 删除 systemd unit 并 disable。"""
        fake_home = tmp_path
        unit_dir = fake_home / ".config/systemd/user"
        unit_dir.mkdir(parents=True)
        unit_path = unit_dir / "news-sentry.service"
        unit_path.write_text("fake unit")

        monkeypatch.setattr(platform, "system", lambda: "Linux")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "uninstall",
                "--pid-file",
                str(tmp_path / "serve.pid"),
            ],
        )
        assert result.exit_code == 0
        assert not unit_path.is_file()
        assert "Uninstall complete" in result.output

    def test_uninstall_purge_removes_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--purge 选项删除数据目录。"""
        fake_home = tmp_path
        data_dir = fake_home / ".news-sentry"
        data_dir.mkdir(parents=True)
        (data_dir / "test_data.txt").write_text("some data")

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "uninstall",
                "--pid-file",
                str(tmp_path / "serve.pid"),
                "--purge",
            ],
        )
        assert result.exit_code == 0
        assert not data_dir.is_dir()
        assert "Purged data directory" in result.output

    def test_uninstall_without_purge_preserves_data(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不带 --purge 时保留数据目录。"""
        fake_home = tmp_path
        data_dir = fake_home / ".news-sentry"
        data_dir.mkdir(parents=True)
        (data_dir / "important.txt").write_text("keep me")

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr(Path, "home", lambda: fake_home)
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "uninstall",
                "--pid-file",
                str(tmp_path / "serve.pid"),
            ],
        )
        assert result.exit_code == 0
        assert data_dir.is_dir()
        assert (data_dir / "important.txt").read_text() == "keep me"

    def test_uninstall_stops_running_server(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """uninstall 应先停止运行中的服务。"""
        if sys.platform == "win32":
            pytest.skip("Unix-specific signal test")
        pid_file = tmp_path / "serve.pid"
        pid_file.write_text("12345")

        monkeypatch.setattr(platform, "system", lambda: "Darwin")
        monkeypatch.setattr("news_sentry.cli.serve._pid_alive", lambda _path: True)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)

        with patch("os.kill") as mock_kill:
            runner = CliRunner()
            result = runner.invoke(
                main,
                [
                    "uninstall",
                    "--pid-file",
                    str(pid_file),
                ],
            )
        assert result.exit_code == 0
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)
