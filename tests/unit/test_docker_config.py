"""Docker 配置验证测试 — 不执行 docker build，仅验证配置文件的一致性和完整性。"""
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


class TestDockerfile:
    """Dockerfile 结构和指令完整性。"""

    def test_dockerfile_exists(self):
        """Dockerfile 文件应存在。"""
        assert (PROJECT_ROOT / "Dockerfile").is_file()

    def test_dockerfile_has_required_stages(self):
        """Dockerfile 应包含 builder + runtime 两个阶段。"""
        content = _read_text("Dockerfile")
        assert "FROM python:3.12-slim AS builder" in content
        assert "FROM python:3.12-slim AS runtime" in content

    def test_dockerfile_copies_source(self):
        """Dockerfile 应将 src/ 复制到镜像。"""
        content = _read_text("Dockerfile")
        assert "COPY src/ src/" in content

    def test_dockerfile_copies_schemas(self):
        """Dockerfile 应包含 COPY schemas/ schemas/（cli doctor 需要）。"""
        content = _read_text("Dockerfile")
        assert "COPY schemas/ schemas/" in content

    def test_dockerfile_copies_config(self):
        """Dockerfile 应包含 COPY config/ config/。"""
        content = _read_text("Dockerfile")
        assert "COPY config/ config/" in content

    def test_dockerfile_copies_entrypoint(self):
        """Dockerfile 应包含 COPY docker-entrypoint.sh。"""
        content = _read_text("Dockerfile")
        assert "docker-entrypoint.sh" in content

    def test_dockerfile_sets_chromium_env(self):
        """Dockerfile 应设置 CHROME_BIN 环境变量。"""
        content = _read_text("Dockerfile")
        assert "CHROME_BIN" in content

    def test_dockerfile_installs_playwright_mcp(self):
        """Dockerfile 应安装 @playwright/mcp（Layer 2 兜底）。"""
        content = _read_text("Dockerfile")
        assert "@playwright/mcp" in content or "playwright" in content

    def test_dockerfile_creates_appuser(self):
        """Dockerfile 应创建非 root 用户 appuser。"""
        content = _read_text("Dockerfile")
        assert "appuser" in content

    def test_dockerfile_entrypoint_exists(self):
        """docker-entrypoint.sh 应存在。"""
        assert (PROJECT_ROOT / "docker-entrypoint.sh").is_file()

    def test_verify_bridge_script_exists(self):
        """docker/verify-bridge.sh 应存在。"""
        assert (PROJECT_ROOT / "docker" / "verify-bridge.sh").is_file()


class TestDockerCompose:
    """docker-compose.yml 配置验证。"""

    def test_compose_exists(self):
        """docker-compose.yml 文件应存在。"""
        assert (PROJECT_ROOT / "docker-compose.yml").is_file()

    def test_compose_valid_yaml(self):
        """docker-compose.yml 应为有效 YAML。"""
        content = _read_text("docker-compose.yml")
        data = yaml.safe_load(content)
        assert data is not None
        assert "services" in data

    def test_compose_has_news_sentry_service(self):
        """docker-compose.yml 应定义 news-sentry 服务。"""
        data = yaml.safe_load(_read_text("docker-compose.yml"))
        assert "news-sentry" in data.get("services", {})

    def test_compose_mounts_data_volume(self):
        """docker-compose.yml 应挂载 data/ 卷。"""
        data = yaml.safe_load(_read_text("docker-compose.yml"))
        volumes = data["services"]["news-sentry"].get("volumes", [])
        volume_paths = [v.split(":")[0] for v in volumes]
        assert "./data" in volume_paths or any("data" in v for v in volume_paths)

    def test_compose_mounts_config_volume(self):
        """docker-compose.yml 应挂载 config/ 卷。"""
        data = yaml.safe_load(_read_text("docker-compose.yml"))
        volumes = data["services"]["news-sentry"].get("volumes", [])
        volume_paths = [v.split(":")[0] for v in volumes]
        assert "./config" in volume_paths or any("config" in v for v in volume_paths)


class TestDockerIgnore:
    """.dockerignore 排除规则验证。"""

    def test_dockerignore_exists(self):
        """.dockerignore 文件应存在。"""
        assert (PROJECT_ROOT / ".dockerignore").is_file()

    def test_dockerignore_excludes_env(self):
        """.dockerignore 应排除 .env* 文件（防止泄露密钥）。"""
        content = _read_text(".dockerignore")
        assert any(".env" in line for line in content.splitlines())

    def test_dockerignore_excludes_tests(self):
        """.dockerignore 应排除 tests/（减少镜像体积）。"""
        content = _read_text(".dockerignore")
        assert any("tests/" in line for line in content.splitlines())

    def test_dockerignore_excludes_git(self):
        """.dockerignore 应排除 .git/。"""
        content = _read_text(".dockerignore")
        assert any(".git" in line for line in content.splitlines())


class TestVerifyBridge:
    """docker/verify-bridge.sh 验证脚本检查。"""

    def test_verify_bridge_checks_key_components(self):
        """verify-bridge.sh 应检查全部 8 个关键组件。"""
        content = _read_text("docker/verify-bridge.sh")
        assert "Chromium" in content
        assert "Xvfb" in content
        assert "ChromeDriver" in content
        assert "Node.js" in content
        assert "Playwright" in content
        assert "OpenCLI" in content
        assert "NMH" in content

    def test_nmh_check_matches_actual_filename(self):
        """verify-bridge.sh 中的 NMH 文件名应与实际文件名一致。"""
        script = _read_text("docker/verify-bridge.sh")
        nmh_dir = PROJECT_ROOT / "docker" / "chrome-native-messaging-host"
        if nmh_dir.is_dir():
            actual_files = list(nmh_dir.glob("*.json"))
            if actual_files:
                actual_name = actual_files[0].name
                assert actual_name in script, (
                    f"verify-bridge.sh 应引用实际 NMH 文件名 '{actual_name}'"
                )


class TestEntrypoint:
    """docker-entrypoint.sh 验证。"""

    def test_entrypoint_starts_xvfb(self):
        """entrypoint 应启动 Xvfb 虚拟显示。"""
        content = _read_text("docker-entrypoint.sh")
        assert "Xvfb" in content

    def test_entrypoint_execs_command(self):
        """entrypoint 应以 exec "$@" 转发命令。"""
        content = _read_text("docker-entrypoint.sh")
        assert 'exec "$@"' in content
