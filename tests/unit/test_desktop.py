"""Tests for news_sentry.cli.desktop — 纯函数 + mock 测试。

不依赖 pywebview/pystray/Pillow（这些在 CI 不可用），
只测试可隔离的纯函数和逻辑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── 配置读写 ──────────────────────────────────────────


class TestDesktopConfig:
    """桌面配置文件的读写。"""

    def test_load_config_missing_file(self, tmp_path: Path) -> None:
        """配置文件不存在时返回空 dict。"""
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", tmp_path / "nope.json"):
            from news_sentry.cli.desktop import _load_desktop_config

            assert _load_desktop_config() == {}

    def test_load_config_valid(self, tmp_path: Path) -> None:
        """正常读取 JSON 配置。"""
        config_path = tmp_path / "desktop.json"
        config_path.write_text(
            json.dumps({"port": 9000, "window_width": 1024}),
            encoding="utf-8",
        )
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", config_path):
            from news_sentry.cli.desktop import _load_desktop_config

            result = _load_desktop_config()
            assert result["port"] == 9000
            assert result["window_width"] == 1024

    def test_load_config_corrupt_json(self, tmp_path: Path) -> None:
        """损坏的 JSON 文件返回空 dict。"""
        config_path = tmp_path / "desktop.json"
        config_path.write_text("{invalid json", encoding="utf-8")
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", config_path):
            from news_sentry.cli.desktop import _load_desktop_config

            assert _load_desktop_config() == {}

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        """保存后读取一致。"""
        config_path = tmp_path / "desktop.json"
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", config_path):
            with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_DIR", tmp_path):
                from news_sentry.cli.desktop import _load_desktop_config, _save_desktop_config

                data = {"port": 8080, "window_width": 1920, "window_height": 1080}
                _save_desktop_config(data)
                loaded = _load_desktop_config()
                assert loaded == data

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        """保存配置时自动创建不存在的目录。"""
        config_dir = tmp_path / "sub" / "dir"
        config_path = config_dir / "desktop.json"
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", config_path):
            with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_DIR", config_dir):
                from news_sentry.cli.desktop import _save_desktop_config

                _save_desktop_config({"test": True})
                assert config_path.is_file()


# ── 版本号解析 ────────────────────────────────────────


class TestVersionParse:
    """版本号解析和比较。"""

    def test_parse_version_normal(self) -> None:
        from news_sentry.cli.desktop import _parse_version

        assert _parse_version("1.7.0") == (1, 7, 0)
        assert _parse_version("2.0.1") == (2, 0, 1)

    def test_parse_version_short(self) -> None:
        from news_sentry.cli.desktop import _parse_version

        assert _parse_version("1.7") == (1, 7)

    def test_parse_version_invalid(self) -> None:
        from news_sentry.cli.desktop import _parse_version

        assert _parse_version("") == (0, 0, 0)
        assert _parse_version("abc") == (0, 0, 0)
        assert _parse_version("1") == (1,)

    def test_version_comparison(self) -> None:
        from news_sentry.cli.desktop import _parse_version

        assert _parse_version("1.8.0") > _parse_version("1.7.1")
        assert _parse_version("2.0.0") > _parse_version("1.99.99")
        assert _parse_version("1.7.0") == _parse_version("1.7.0")


# ── 更新检测 ──────────────────────────────────────────


class TestCheckUpdate:
    """GitHub Release 更新检测。"""

    def test_check_update_newer_available(self) -> None:
        """远程版本更高时返回新版本号。"""
        from news_sentry.cli.desktop import _check_update

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"tag_name": "v99.99.99"}).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _check_update()
            assert result == "99.99.99"

    def test_check_update_already_latest(self) -> None:
        """远程版本不高于当前时返回 None。"""
        from news_sentry.cli.desktop import _check_update

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"tag_name": "v0.0.1"}).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _check_update()
            assert result is None

    def test_check_update_network_error(self) -> None:
        """网络错误返回 None。"""
        from news_sentry.cli.desktop import _check_update

        with patch("urllib.request.urlopen", side_effect=Exception("network error")):
            result = _check_update()
            assert result is None

    def test_check_update_empty_tag(self) -> None:
        """空 tag_name 返回 None。"""
        from news_sentry.cli.desktop import _check_update

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"tag_name": ""}).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _check_update()
            assert result is None


# ── 下载更新 ──────────────────────────────────────────


class TestDownloadUpdate:
    """更新下载逻辑。"""

    def test_download_update_success(self, tmp_path: Path) -> None:
        """成功下载返回文件路径。"""
        from news_sentry.cli.desktop import _download_update

        mock_response = MagicMock()
        mock_response.read.side_effect = [b"binary_data", b""]
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            with patch("click.echo"):
                result = _download_update("1.8.0", dest_dir=tmp_path)
                assert result is not None
                assert result.is_file()
                content = result.read_bytes()
                assert content == b"binary_data"

    def test_download_update_failure(self, tmp_path: Path) -> None:
        """下载失败返回 None。"""
        from news_sentry.cli.desktop import _download_update

        with patch("urllib.request.urlopen", side_effect=Exception("fail")):
            with patch("click.echo"):
                result = _download_update("1.8.0", dest_dir=tmp_path)
                assert result is None


# ── 原生通知 API (JS bridge) ──────────────────────────


class TestNativeNotifyApi:
    """JS bridge 原生通知 API 测试。"""

    def test_download_and_install_no_version(self) -> None:
        """没有可用更新时返回提示。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        api = _NativeNotifyApi()
        api.latest_version = None
        result = api.download_and_install()
        assert result == "No update available"

    def test_download_and_install_success(self) -> None:
        """更新下载安装流程。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        api = _NativeNotifyApi()
        api.latest_version = "99.0.0"

        with patch("news_sentry.cli.desktop._download_update", return_value=Path("/tmp/fake")):  # noqa: S108
            with patch("news_sentry.cli.desktop._install_update"):
                result = api.download_and_install()
                assert result == "Restarting..."

    def test_download_and_install_download_fails(self) -> None:
        """更新下载失败时返回错误。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        api = _NativeNotifyApi()
        api.latest_version = "99.0.0"

        with patch("news_sentry.cli.desktop._download_update", return_value=None):
            result = api.download_and_install()
            assert result == "Download failed"

    def test_notify_macos(self) -> None:
        """macOS 通知调用 osascript。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.Popen") as mock_popen:
                api = _NativeNotifyApi()
                api.notify("Title", "Body text")
                mock_popen.assert_called_once()
                args = mock_popen.call_args[0][0]
                assert "osascript" in args

    def test_notify_linux(self) -> None:
        """Linux 通知调用 notify-send。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.Popen") as mock_popen:
                api = _NativeNotifyApi()
                api.notify("Title", "Body text")
                mock_popen.assert_called_once()
                args = mock_popen.call_args[0][0]
                assert "notify-send" in args

    def test_notify_error_silent(self) -> None:
        """通知失败不抛异常。"""
        from news_sentry.cli.desktop import _NativeNotifyApi

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.Popen", side_effect=Exception("fail")):
                api = _NativeNotifyApi()
                # 不应抛异常
                api.notify("Title", "Body")


# ── OS 信息 ──────────────────────────────────────────


class TestOsInfo:
    """跨平台 OS 描述字符串。"""

    def test_macos(self) -> None:
        from news_sentry.cli.desktop import _os_info

        with patch("platform.system", return_value="Darwin"):
            with patch("platform.mac_ver", return_value=("15.0", "", "")):
                result = _os_info()
                assert "macOS" in result

    def test_linux(self) -> None:
        from news_sentry.cli.desktop import _os_info

        with patch("platform.system", return_value="Linux"):
            with patch("platform.release", return_value="6.1.0"):
                with patch("builtins.open", side_effect=OSError("no os-release")):
                    result = _os_info()
                    assert "Linux" in result

    def test_linux_with_os_release(self, tmp_path: Path) -> None:
        from news_sentry.cli.desktop import _os_info

        os_release = tmp_path / "os-release"
        os_release.write_text('PRETTY_NAME="Ubuntu 24.04"\n')

        with patch("platform.system", return_value="Linux"):
            with patch("platform.release", return_value="6.1.0"):
                with patch("news_sentry.cli.desktop.Path") as mock_path:
                    mock_path.return_value.read_text.return_value = 'PRETTY_NAME="Ubuntu 24.04"\n'
                    # 由于 Path("/etc/os-release") 被替换，直接测试
                    result = _os_info()
                    assert "Ubuntu" in result


# ── 安装更新 ──────────────────────────────────────────


class TestInstallUpdate:
    """更新安装逻辑 — 使用真实文件系统，不 mock Path。"""

    def test_install_update_creates_backup(self, tmp_path: Path) -> None:
        """安装前创建 .bak 备份。"""
        from news_sentry.cli.desktop import _install_update

        binary = tmp_path / "new-binary"
        binary.write_bytes(b"new_content")
        fake_exe = tmp_path / "news-sentry"
        fake_exe.write_bytes(b"old_content")

        with patch("news_sentry.cli.desktop.sys") as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = str(fake_exe)
            mock_sys.argv = ["test"]
            mock_sys.platform = "darwin"
            with patch("os.execv"):
                _install_update(binary)

        # 验证文件被替换
        assert fake_exe.read_bytes() == b"new_content"
        # 验证备份被创建
        backup = fake_exe.with_suffix(".bak")
        assert backup.read_bytes() == b"old_content"

    def test_install_update_exe_not_exists(self, tmp_path: Path) -> None:
        """当前可执行文件不存在时安全退出。"""
        from news_sentry.cli.desktop import _install_update

        binary = tmp_path / "new-binary"
        binary.write_bytes(b"new")
        fake_exe = tmp_path / "nonexistent"

        with patch("news_sentry.cli.desktop.sys") as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = str(fake_exe)
            mock_sys.argv = ["test"]
            mock_sys.platform = "darwin"
            with patch("click.echo") as mock_echo:
                _install_update(binary)
                assert any("不存在" in str(c) for c in mock_echo.call_args_list)

    def test_install_update_rollback_on_failure(self, tmp_path: Path) -> None:
        """安装失败时回滚到备份。"""
        from news_sentry.cli.desktop import _install_update

        binary = tmp_path / "new-binary"
        binary.write_bytes(b"new")
        fake_exe = tmp_path / "news-sentry"
        fake_exe.write_bytes(b"old")

        copy_count = [0]
        original_copy = __import__("shutil").copy2

        def selective_fail(src, dst):
            copy_count[0] += 1
            if copy_count[0] == 2:
                raise OSError("disk full")
            return original_copy(src, dst)

        with patch("news_sentry.cli.desktop.sys") as mock_sys:
            mock_sys.frozen = True
            mock_sys.executable = str(fake_exe)
            mock_sys.argv = ["test"]
            mock_sys.platform = "darwin"
            with patch("os.execv"):
                with patch("shutil.copy2", side_effect=selective_fail):
                    with patch("click.echo"):
                        _install_update(binary)

        # 验证回滚 — 备份恢复原文件
        assert fake_exe.read_bytes() == b"old"


# ── CLI 命令 ──────────────────────────────────────────


class TestDesktopCommand:
    """desktop CLI 命令测试。"""

    def test_missing_pywebview(self) -> None:
        """缺少 pywebview 时输出错误并退出。"""
        from click.testing import CliRunner

        from news_sentry.cli import main

        runner = CliRunner()
        with patch.dict(sys.modules, {"webview": None}):
            result = runner.invoke(main, ["desktop"])
            assert result.exit_code != 0
            assert "pywebview" in result.output.lower() or "error" in result.output.lower()

    def test_autostart_install_flag(self) -> None:
        """--autostart 标志调用安装函数。"""
        from click.testing import CliRunner

        from news_sentry.cli import main

        runner = CliRunner()
        with patch("news_sentry.cli.desktop._autostart_install") as mock_install:
            result = runner.invoke(main, ["desktop", "--autostart"])
            mock_install.assert_called_once()
            assert result.exit_code == 0

    def test_no_autostart_flag(self) -> None:
        """--no-autostart 标志调用卸载函数。"""
        from click.testing import CliRunner

        from news_sentry.cli import main

        runner = CliRunner()
        with patch("news_sentry.cli.desktop._autostart_uninstall") as mock_uninstall:
            result = runner.invoke(main, ["desktop", "--no-autostart"])
            mock_uninstall.assert_called_once()
            assert result.exit_code == 0


# ── 服务器线程管理 ──────────────────────────────────


class TestServerLifecycle:
    """服务器启动/停止逻辑。"""

    def test_start_server_creates_thread(self) -> None:
        """_start_server 创建 daemon 线程。"""
        from news_sentry.cli.desktop import _start_server

        with patch("news_sentry.cli.desktop._run_server"):
            thread = _start_server("127.0.0.1", 9999)
            assert thread.daemon is True
            assert thread.name == "news-sentry-uvicorn"

    def test_start_server_stores_thread_ref(self) -> None:
        """启动后线程引用被保存。"""
        import news_sentry.cli.desktop as mod

        with patch.object(mod, "_server_thread", None):
            with patch("news_sentry.cli.desktop._run_server"):
                thread = mod._start_server("127.0.0.1", 9999)
                assert mod._server_thread is thread


# ── 托盘图标 ────────────────────────────────────────


class TestTrayIcon:
    """系统托盘图标相关逻辑。"""

    def test_stop_tray_none(self) -> None:
        """没有托盘图标时不报错。"""
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _stop_tray

        with patch.object(mod, "_tray_icon", None):
            _stop_tray()  # 不应抛异常

    def test_stop_tray_calls_stop(self) -> None:
        """有托盘图标时调用 stop()。"""
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _stop_tray

        mock_icon = MagicMock()
        with patch.object(mod, "_tray_icon", mock_icon):
            _stop_tray()
            mock_icon.stop.assert_called_once()

    def test_stop_tray_exception_silent(self) -> None:
        """stop() 抛异常时不传播。"""
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _stop_tray

        mock_icon = MagicMock()
        mock_icon.stop.side_effect = RuntimeError("tray error")
        with patch.object(mod, "_tray_icon", mock_icon):
            _stop_tray()  # 不应抛异常


# ── 打开目录 ────────────────────────────────────────


class TestOpenDir:
    """跨平台打开目录。"""

    def test_open_dir_macos(self) -> None:
        from news_sentry.cli.desktop import _open_dir

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.Popen") as mock_popen:
                _open_dir("/tmp/test")  # noqa: S108
                mock_popen.assert_called_once()
                assert "open" in mock_popen.call_args[0][0]

    def test_open_dir_linux(self) -> None:
        from news_sentry.cli.desktop import _open_dir

        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.Popen") as mock_popen:
                _open_dir("/tmp/test")  # noqa: S108
                mock_popen.assert_called_once()
                assert "xdg-open" in mock_popen.call_args[0][0]

    def test_open_dir_error_silent(self) -> None:
        from news_sentry.cli.desktop import _open_dir

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.Popen", side_effect=Exception("fail")):
                _open_dir("/tmp/test")  # noqa: S108  # 不应抛异常


# ── 自启动 ──────────────────────────────────────────


class TestAutostart:
    """开机自启动管理 — 用 os.environ 重定向 HOME 目录。"""

    def _fake_home(self, tmp_path):
        """创建一个 mock home 目录环境。"""
        import news_sentry.cli.desktop as mod

        original_home = mod.Path.home
        mod.Path.home = lambda: tmp_path
        return original_home

    def _restore_home(self, original_home):
        import news_sentry.cli.desktop as mod

        mod.Path.home = original_home

    def test_autostart_install_macos(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_install

        orig = self._fake_home(tmp_path)
        try:
            with patch("platform.system", return_value="Darwin"):
                with patch.object(mod, "Path") as mock_path:
                    mock_path.home.return_value = tmp_path
                    mock_path.return_value.__truediv__ = lambda s, o: tmp_path / o
                    with patch("subprocess.run"):
                        with patch("click.echo"):
                            _autostart_install(8000)
        finally:
            self._restore_home(orig)

    def test_autostart_install_linux(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_install

        orig = mod.Path.home
        mod.Path.home = lambda: tmp_path
        try:
            with patch("platform.system", return_value="Linux"):
                with patch("click.echo"):
                    _autostart_install(8000)
                    entry = tmp_path / ".config" / "autostart" / "news-sentry.desktop"
                    assert entry.is_file()
        finally:
            mod.Path.home = orig

    def test_autostart_uninstall_macos_no_file(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_uninstall

        orig = mod.Path.home
        mod.Path.home = lambda: tmp_path
        try:
            with patch("platform.system", return_value="Darwin"):
                with patch("click.echo") as mock_echo:
                    _autostart_uninstall()
                    assert any("未找到" in str(c) for c in mock_echo.call_args_list)
        finally:
            mod.Path.home = orig

    def test_autostart_uninstall_macos_with_file(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_uninstall

        plist_dir = tmp_path / "Library" / "LaunchAgents"
        plist_dir.mkdir(parents=True, exist_ok=True)
        plist_path = plist_dir / "com.news-sentry.desktop.plist"
        plist_path.write_text("dummy")
        orig = mod.Path.home
        mod.Path.home = lambda: tmp_path
        try:
            with patch("platform.system", return_value="Darwin"):
                with patch("subprocess.run"):
                    with patch("click.echo"):
                        _autostart_uninstall()
                        assert not plist_path.exists()
        finally:
            mod.Path.home = orig

    def test_autostart_uninstall_linux_no_file(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_uninstall

        orig = mod.Path.home
        mod.Path.home = lambda: tmp_path
        try:
            with patch("platform.system", return_value="Linux"):
                with patch("click.echo") as mock_echo:
                    _autostart_uninstall()
                    assert any("未找到" in str(c) for c in mock_echo.call_args_list)
        finally:
            mod.Path.home = orig

    def test_autostart_uninstall_linux_with_file(self, tmp_path: Path) -> None:
        import news_sentry.cli.desktop as mod
        from news_sentry.cli.desktop import _autostart_uninstall

        autostart_dir = tmp_path / ".config" / "autostart"
        autostart_dir.mkdir(parents=True, exist_ok=True)
        entry_path = autostart_dir / "news-sentry.desktop"
        entry_path.write_text("dummy")
        orig = mod.Path.home
        mod.Path.home = lambda: tmp_path
        try:
            with patch("platform.system", return_value="Linux"):
                with patch("click.echo"):
                    _autostart_uninstall()
                    assert not entry_path.exists()
        finally:
            mod.Path.home = orig


class TestDoQuit:
    """应用退出逻辑。"""

    def test_do_quit_saves_config(self, tmp_path: Path) -> None:
        """退出时保存窗口状态。"""
        from news_sentry.cli.desktop import _do_quit

        mock_window = MagicMock()
        mock_window.width = 1024
        mock_window.height = 768
        mock_window.x = 100
        mock_window.y = 200

        config_path = tmp_path / "desktop.json"
        with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_PATH", config_path):
            with patch("news_sentry.cli.desktop._DESKTOP_CONFIG_DIR", tmp_path):
                with patch("news_sentry.cli.desktop._stop_tray"):
                    with patch("os._exit") as mock_exit:
                        _do_quit(mock_window, "/tmp/data")  # noqa: S108
                        mock_exit.assert_called_once_with(0)

        # 验证配置被保存
        saved = json.loads(config_path.read_text())
        assert saved["window_width"] == 1024
        assert saved["window_height"] == 768

    def test_do_quit_none_window(self) -> None:
        """窗口为 None 时不崩溃。"""
        from news_sentry.cli.desktop import _do_quit

        with patch("news_sentry.cli.desktop._stop_tray"):
            with patch("os._exit"):
                _do_quit(None, "/tmp/data")  # noqa: S108
