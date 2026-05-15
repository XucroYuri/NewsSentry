from pathlib import Path

import yaml

from news_sentry.core.config_cache import ConfigCache


class TestConfigCache:
    """配置 TTL 缓存测试。"""

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    def test_cache_hit_returns_same_result(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"key": "value"})

        result1 = cache.load_yaml(yaml_path)
        result2 = cache.load_yaml(yaml_path)
        assert result1 == result2
        assert result1["key"] == "value"

    def test_cache_invalidates_on_clear(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"version": 1})

        result1 = cache.load_yaml(yaml_path)
        assert result1["version"] == 1

        self._write_yaml(yaml_path, {"version": 2})
        cache.clear()

        result2 = cache.load_yaml(yaml_path)
        assert result2["version"] == 2

    def test_cache_returns_none_for_missing_file(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        result = cache.load_yaml(tmp_path / "nonexistent.yaml")
        assert result is None

    def test_cache_stores_multiple_files(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        path_a = tmp_path / "a.yaml"
        path_b = tmp_path / "b.yaml"
        self._write_yaml(path_a, {"name": "a"})
        self._write_yaml(path_b, {"name": "b"})

        assert cache.load_yaml(path_a)["name"] == "a"
        assert cache.load_yaml(path_b)["name"] == "b"

    def test_cache_hit_counts(self, tmp_path: Path) -> None:
        """缓存命中不应重复读文件。"""
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"key": "value"})

        cache.load_yaml(yaml_path)
        cache.load_yaml(yaml_path)
        cache.load_yaml(yaml_path)

        assert cache.hits == 2
        assert cache.misses == 1

    def test_reload_delegates_to_clear(self, tmp_path: Path) -> None:
        cache = ConfigCache(ttl=60, maxsize=128)
        yaml_path = tmp_path / "test.yaml"
        self._write_yaml(yaml_path, {"v": 1})
        cache.load_yaml(yaml_path)

        self._write_yaml(yaml_path, {"v": 2})
        cache.reload()

        result = cache.load_yaml(yaml_path)
        assert result["v"] == 2
