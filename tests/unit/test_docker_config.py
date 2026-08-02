"""Docker 配置验证测试 — 不执行 docker build，仅验证配置文件的一致性和完整性。"""

import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read_text(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _docker_env_value(name: str) -> str:
    match = re.search(rf"^ENV\s+{re.escape(name)}=(\S+)\s*$", _read_text("Dockerfile"), re.M)
    assert match is not None, f"Dockerfile must define ENV {name}"
    return match.group(1)


def _compose_service() -> dict:
    data = yaml.safe_load(_read_text("docker-compose.yml"))
    return data["services"]["news-sentry"]


def _compose_environment() -> dict[str, str]:
    environment = _compose_service().get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    result: dict[str, str] = {}
    for item in environment:
        key, _, value = str(item).partition("=")
        result[key] = value
    return result


class TestDockerfile:
    """Dockerfile v2 结构和指令完整性。"""

    def test_dockerfile_exists(self):
        """Dockerfile 文件应存在。"""
        assert (PROJECT_ROOT / "Dockerfile").is_file()

    def test_dockerfile_has_required_stages(self):
        """Dockerfile 应包含 builder + runtime 两个阶段。"""
        content = _read_text("Dockerfile")
        assert "ARG PYTHON_BASE_IMAGE=mirror.gcr.io/library/python:3.12-slim" in content
        assert "FROM ${PYTHON_BASE_IMAGE} AS builder" in content
        assert "FROM ${PYTHON_BASE_IMAGE} AS runtime" in content

    def test_dockerfile_copies_source(self):
        """Dockerfile 应将 src/ 复制到镜像。"""
        content = _read_text("Dockerfile")
        assert "COPY src/ src/" in content

    def test_dockerfile_copies_schemas(self):
        """Dockerfile 运行时阶段应包含 COPY schemas/。"""
        content = _read_text("Dockerfile")
        assert "COPY schemas/" in content

    def test_dockerfile_copies_config(self):
        """Dockerfile 运行时阶段应包含 COPY config/。"""
        content = _read_text("Dockerfile")
        assert "COPY config/" in content

    def test_dockerfile_copies_entrypoint(self):
        """Dockerfile 应包含 COPY docker-entrypoint.sh。"""
        content = _read_text("Dockerfile")
        assert "docker-entrypoint.sh" in content

    def test_dockerfile_no_browser_deps(self):
        """v2 Dockerfile 不应包含 Chromium/Playwright/Node.js/OpenCLI。"""
        content = _read_text("Dockerfile")
        assert "chromium" not in content
        assert "playwright" not in content
        assert "nodejs" not in content
        assert "opencli" not in content

    def test_dockerfile_installs_api_extra_without_proxy_extra(self):
        """运行时镜像只安装 API extra，不带 proxy socks 依赖。"""
        content = _read_text("Dockerfile")
        assert '".[api]"' in content
        assert '".[api,proxy]"' not in content

    def test_dockerfile_strips_python_bytecode_caches(self):
        """builder/runtime 阶段都应清理 Python bytecode 缓存。"""
        content = _read_text("Dockerfile")
        assert 'find /install -name "*.pyc" -delete' in content
        assert 'find /install -name "__pycache__" -type d' in content
        assert 'find /usr/local/lib/python3.12 -name "__pycache__" -type d' in content
        assert 'find /usr/local/lib/python3.12 -name "*.pyc" -delete' in content

    def test_dockerfile_creates_appuser(self):
        """Dockerfile 应创建非 root 用户 appuser。"""
        content = _read_text("Dockerfile")
        assert "appuser" in content

    def test_dockerfile_entrypoint_exists(self):
        """docker-entrypoint.sh 应存在。"""
        assert (PROJECT_ROOT / "docker-entrypoint.sh").is_file()

    def test_dockerfile_healthcheck_includes_api_v1_path(self):
        """v2 Dockerfile 健康检查应使用 /api/v1/health。"""
        content = _read_text("Dockerfile")
        assert "/api/v1/health" in content

    def test_dockerfile_default_profile_exists_and_is_cloudflare(self):
        """Container 默认 profile 必须绑定真实 Cloudflare 部署 profile。"""
        profile_id = _docker_env_value("NEWSSENTRY_PROFILE")
        profile_path = PROJECT_ROOT / "config" / "profiles" / f"{profile_id}.yaml"

        assert profile_id == "cloudflare"
        assert profile_path.is_file()


class TestDockerCompose:
    """docker-compose.yml v2 配置验证。"""

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

    def test_compose_has_rss_bridge_service(self):
        """v2 docker-compose.yml 应定义 rss-bridge 服务。"""
        data = yaml.safe_load(_read_text("docker-compose.yml"))
        assert "rss-bridge" in data.get("services", {})

    def test_compose_news_sentry_builds_from_context(self):
        """news-sentry 服务应使用本地 build 而非外部镜像。"""
        svc = _compose_service()
        assert "build" in svc

    def test_compose_mounts_config_volume(self):
        """docker-compose.yml 应挂载 config/ 为只读卷。"""
        volumes = _compose_service().get("volumes", [])
        config_volumes = [v for v in volumes if "config" in v]
        assert len(config_volumes) > 0

    def test_compose_profile_override_is_valid_when_present(self):
        """compose 不得覆盖为不存在 profile；缺省时继承 Dockerfile。"""
        environment = _compose_environment()
        if "NEWSSENTRY_PROFILE" not in environment:
            return

        profile_id = environment["NEWSSENTRY_PROFILE"]
        profile_path = PROJECT_ROOT / "config" / "profiles" / f"{profile_id}.yaml"

        assert profile_id == _docker_env_value("NEWSSENTRY_PROFILE")
        assert profile_path.is_file()


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


class TestEntrypoint:
    """docker-entrypoint.sh v2 验证。"""

    def test_entrypoint_execs_command(self):
        """entrypoint 应以 exec "$@" 转发命令。"""
        content = _read_text("docker-entrypoint.sh")
        assert 'exec "$@"' in content

    def test_entrypoint_has_no_xvfb(self):
        """v2 entrypoint 不应包含 Xvfb。"""
        content = _read_text("docker-entrypoint.sh")
        assert "Xvfb" not in content


class TestRssBridgeConfig:
    """RSS-Bridge 配置文件验证。"""

    def test_whitelist_exists(self):
        """rss-bridge/whitelist.txt 应存在。"""
        assert (PROJECT_ROOT / "rss-bridge" / "whitelist.txt").is_file()

    def test_config_php_exists(self):
        """rss-bridge/config.ini.php 应存在。"""
        assert (PROJECT_ROOT / "rss-bridge" / "config.ini.php").is_file()

    def test_config_php_is_valid(self):
        """rss-bridge/config.ini.php 应为有效 PHP 配置。"""
        content = _read_text("rss-bridge/config.ini.php")
        assert "<?php" in content
        assert "return [" in content

    def test_whitelist_allows_all(self):
        """whitelist.txt 应允许所有 Bridge（*）。"""
        content = _read_text("rss-bridge/whitelist.txt").strip()
        assert content == "*"
