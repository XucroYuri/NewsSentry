"""config.py 模块测试 — ConfigLoader + ResolvedConfig"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema.exceptions import ValidationError

from news_sentry.core.config import ConfigLoader, ResolvedConfig

# ── helpers ────────────────────────────────────────────────────

def _write_yaml(path: Path, data: dict, schema_ref: str | None = None) -> None:
    """写入 YAML 文件，可选带 # Schema: 头部注释。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if schema_ref is not None:
        lines.append(f"# Schema: {schema_ref}")
    lines.append(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_json_schema(path: Path, schema: dict) -> None:
    """写入 JSON Schema 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2), encoding="utf-8")


def _make_minimal_target(**overrides) -> dict:
    data = {
        "target_id": "test-target",
        "display_name": "测试目标",
        "language_scope": {"primary": "it", "secondary": ["en"], "output": "zh"},
        "timezone": "Europe/Rome",
        "source_channel_refs": [],
    }
    data.update(overrides)
    return data


def _make_minimal_source(source_id: str = "test-source", **overrides) -> dict:
    data = {
        "source_id": source_id,
        "display_name": f"测试源 {source_id}",
        "type": "rss",
        "url": "https://example.com/rss",
        "credibility_base": 0.8,
        "fetch_interval_minutes": 15,
        "max_items_per_run": 50,
        "timeout_seconds": 30,
        "enabled": True,
        "health": {"last_success_at": None, "consecutive_failures": 0},
    }
    data.update(overrides)
    return data


# ── fixtures ───────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """创建最小项目结构，含 config/ 和 schemas/ 目录。"""
    (tmp_path / "config").mkdir()
    (tmp_path / "schemas").mkdir()
    return tmp_path


@pytest.fixture
def loader(project_root: Path) -> ConfigLoader:
    return ConfigLoader(project_root)


# ── ResolvedConfig ─────────────────────────────────────────────

class TestResolvedConfig:
    def test_basic_fields(self):
        cfg = ResolvedConfig(
            target={"target_id": "italy"},
            sources=[{"source_id": "ansa"}],
            filter_rules={"threshold": 50},
        )
        assert cfg.target_id == "italy"
        assert len(cfg.sources) == 1
        assert cfg.sources[0]["source_id"] == "ansa"
        assert cfg.filter_rules["threshold"] == 50

    def test_defaults(self):
        cfg = ResolvedConfig(target={"target_id": "x"})
        assert cfg.sources == []
        assert cfg.filter_rules == {}
        assert cfg.classification_rules == {}
        assert cfg.sandbox_policy == {}
        assert cfg.provider_routes == {}
        assert cfg.output_destinations == {}


# ── _extract_schema_ref ───────────────────────────────────────

class TestExtractSchemaRef:
    def test_extracts_schema_ref(self):
        text = "# Schema: ../../schemas/targetconfig.schema.json\nkey: val\n"
        assert ConfigLoader._extract_schema_ref(text) == "../../schemas/targetconfig.schema.json"

    def test_no_schema_returns_none(self):
        assert ConfigLoader._extract_schema_ref("key: val\n") is None

    def test_empty_text(self):
        assert ConfigLoader._extract_schema_ref("") is None

    def test_relative_path(self):
        text = "# Schema: ../schemas/foo.schema.json\ndata: yes\n"
        assert ConfigLoader._extract_schema_ref(text) == "../schemas/foo.schema.json"

    def test_multiple_lines_picks_first(self):
        text = "# Schema: first.yaml\n# Schema: second.yaml\ndata: yes\n"
        assert ConfigLoader._extract_schema_ref(text) == "first.yaml"

    def test_schema_comment_not_at_start(self):
        text = "key: val\n# Schema: targetconfig.schema.json\n"
        assert ConfigLoader._extract_schema_ref(text) == "targetconfig.schema.json"


# ── _load_yaml ────────────────────────────────────────────────

class TestLoadYaml:
    def test_loads_basic_yaml(self, loader, project_root):
        path = project_root / "test.yaml"
        _write_yaml(path, {"key": "value"})
        assert loader._load_yaml(path) == {"key": "value"}

    def test_empty_file_returns_empty_dict(self, loader, project_root):
        path = project_root / "empty.yaml"
        path.write_text("", encoding="utf-8")
        assert loader._load_yaml(path) == {}

    def test_file_not_found(self, loader, project_root):
        with pytest.raises(FileNotFoundError):
            loader._load_yaml(project_root / "missing.yaml")

    def test_nested_structures(self, loader, project_root):
        path = project_root / "nested.yaml"
        _write_yaml(path, {"parent": {"child": [1, 2, 3]}})
        assert loader._load_yaml(path) == {"parent": {"child": [1, 2, 3]}}


# ── _deep_merge ───────────────────────────────────────────────

class TestDeepMerge:
    @pytest.fixture
    def loader_fixture(self, project_root):
        return ConfigLoader(project_root)

    def test_dict_merge(self, loader_fixture):
        base = {"a": 1, "b": {"c": 2}}
        override = {"b": {"d": 3}, "e": 4}
        result = loader_fixture._deep_merge(base, override)
        assert result == {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}

    def test_list_replaces(self, loader_fixture):
        base = {"items": [1, 2, 3]}
        override = {"items": [4, 5]}
        result = loader_fixture._deep_merge(base, override)
        assert result["items"] == [4, 5]

    def test_scalar_overrides(self, loader_fixture):
        base = {"key": "old"}
        override = {"key": "new"}
        assert loader_fixture._deep_merge(base, override) == {"key": "new"}

    def test_override_adds_new_keys(self, loader_fixture):
        base = {"a": 1}
        override = {"b": 2}
        assert loader_fixture._deep_merge(base, override) == {"a": 1, "b": 2}

    def test_deep_nested_merge(self, loader_fixture):
        base = {"level1": {"level2": {"a": 1, "b": 2}}}
        override = {"level1": {"level2": {"b": 99, "c": 3}}}
        result = loader_fixture._deep_merge(base, override)
        assert result == {"level1": {"level2": {"a": 1, "b": 99, "c": 3}}}

    def test_mixed_types_override(self, loader_fixture):
        base = {"key": {"nested": True}}
        override = {"key": "flat_string"}
        assert loader_fixture._deep_merge(base, override) == {"key": "flat_string"}


# ── _resolve_schema_path ──────────────────────────────────────

class TestResolveSchemaPath:
    def test_resolves_relative_to_yaml(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "my.schema.json", {"type": "object"})

        yaml_dir = project_root / "config" / "targets"
        yaml_dir.mkdir(parents=True)
        yaml_path = yaml_dir / "test.yaml"
        yaml_path.write_text("# Schema: ../../schemas/my.schema.json\nkey: val", encoding="utf-8")

        result = loader._resolve_schema_path(yaml_path)
        assert result is not None
        assert result.name == "my.schema.json"

    def test_fallback_to_schemas_dir(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "fallback.schema.json", {"type": "object"})

        yaml_dir = project_root / "config" / "deep" / "nested"
        yaml_dir.mkdir(parents=True)
        yaml_path = yaml_dir / "test.yaml"
        schema_ref = "# Schema: ../../../wrong/fallback.schema.json\nkey: val"
        yaml_path.write_text(schema_ref, encoding="utf-8")

        result = loader._resolve_schema_path(yaml_path)
        assert result is not None
        assert result.name == "fallback.schema.json"

    def test_no_schema_comment_returns_none(self, loader, project_root):
        yaml_dir = project_root / "config"
        yaml_path = yaml_dir / "no_schema.yaml"
        yaml_path.write_text("key: val", encoding="utf-8")
        assert loader._resolve_schema_path(yaml_path) is None

    def test_schema_not_found_returns_none(self, loader, project_root):
        yaml_dir = project_root / "config"
        yaml_path = yaml_dir / "bad.yaml"
        yaml_path.write_text("# Schema: missing_file.schema.json\nkey: val", encoding="utf-8")
        assert loader._resolve_schema_path(yaml_path) is None


# ── _validate ──────────────────────────────────────────────────

class TestValidate:
    def test_valid_data_passes(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        schema_path = schemas_dir / "test.schema.json"
        _write_json_schema(schema_path, {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        })
        loader._validate({"name": "hello"}, schema_path)

    def test_invalid_data_raises(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        schema_path = schemas_dir / "test.schema.json"
        _write_json_schema(schema_path, {
            "type": "object",
            "properties": {"age": {"type": "integer", "minimum": 0}},
        })
        with pytest.raises(ValidationError):
            loader._validate({"age": -1}, schema_path)

    def test_missing_schema_file(self, loader, project_root):
        with pytest.raises(FileNotFoundError):
            loader._validate({}, project_root / "schemas" / "nope.schema.json")


# ── _validate_resolved_schema ──────────────────────────────────

class TestValidateResolvedSchema:
    def test_skips_when_no_schema(self, loader, project_root):
        path = project_root / "no_schema.yaml"
        path.write_text("key: val", encoding="utf-8")
        loader._validate_resolved_schema({"anything": True}, path)

    def test_validates_with_schema(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "s.schema.json", {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        })
        yaml_path = project_root / "with_schema.yaml"
        yaml_path.write_text("# Schema: schemas/s.schema.json\nname: test", encoding="utf-8")
        loader._validate_resolved_schema({"name": "test"}, yaml_path)

    def test_validation_failure_raises(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "s.schema.json", {
            "type": "object",
            "required": ["must_exist"],
        })
        yaml_path = project_root / "fail.yaml"
        yaml_path.write_text("# Schema: schemas/s.schema.json\nfoo: bar", encoding="utf-8")
        with pytest.raises(ValidationError):
            loader._validate_resolved_schema({"foo": "bar"}, yaml_path)


# ── _load_referenced_config ───────────────────────────────────

class TestLoadReferencedConfig:
    def test_loads_by_relative_to_config_root(self, loader, project_root):
        ref_dir = project_root / "config" / "filters"
        ref_dir.mkdir(parents=True)
        _write_yaml(ref_dir / "rules.yaml", {"threshold": 80})

        result = loader._load_referenced_config(
            "config/filters/rules.yaml",
            project_root / "config" / "targets" / "test.yaml"
        )
        assert result == {"threshold": 80}

    def test_loads_by_relative_to_context_parent(self, loader, project_root):
        targets_dir = project_root / "config" / "targets"
        targets_dir.mkdir(parents=True)
        _write_yaml(targets_dir / "rules.yaml", {"threshold": 60})

        result = loader._load_referenced_config(
            "rules.yaml",
            targets_dir / "test.yaml"
        )
        assert result == {"threshold": 60}

    def test_none_ref_returns_empty_dict(self, loader):
        result = loader._load_referenced_config(None, Path("/fake/path.yaml"))
        assert result == {}

    def test_missing_ref_returns_empty_dict(self, loader, project_root):
        result = loader._load_referenced_config(
            "missing.yaml",
            project_root / "config" / "targets" / "test.yaml"
        )
        assert result == {}

    def test_validates_with_schema(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "filter.schema.json", {
            "type": "object",
            "required": ["threshold"],
            "properties": {"threshold": {"type": "integer"}},
        })

        ref_dir = project_root / "config" / "filters"
        ref_dir.mkdir(parents=True)
        _write_yaml(ref_dir / "rules.yaml", {"threshold": 80},
                    schema_ref="../../schemas/filter.schema.json")

        result = loader._load_referenced_config(
            "config/filters/rules.yaml",
            project_root / "config" / "targets" / "test.yaml"
        )
        assert result == {"threshold": 80}


# ── _load_sources ─────────────────────────────────────────────

class TestLoadSources:
    def test_loads_multiple_sources(self, loader, project_root):
        sources_dir = project_root / "config" / "sources" / "my-target"
        sources_dir.mkdir(parents=True)
        _write_yaml(sources_dir / "src1.yaml", _make_minimal_source("src1"))
        _write_yaml(sources_dir / "src2.yaml", _make_minimal_source("src2"))

        results = loader._load_sources("my-target", ["src1", "src2"])
        assert len(results) == 2
        assert {r["source_id"] for r in results} == {"src1", "src2"}

    def test_empty_source_ids(self, loader):
        assert loader._load_sources("any", []) == []

    def test_missing_source_raises(self, loader, project_root):
        sources_dir = project_root / "config" / "sources" / "my-target"
        sources_dir.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="Source 配置文件不存在"):
            loader._load_sources("my-target", ["ghost"])

    def test_validates_source_against_schema(self, loader, project_root):
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        _write_json_schema(schemas_dir / "sourcechannel.schema.json", {
            "type": "object",
            "required": ["source_id"],
            "properties": {"source_id": {"type": "string"}},
        })

        sources_dir = project_root / "config" / "sources" / "my-target"
        sources_dir.mkdir(parents=True)
        _write_yaml(sources_dir / "s.yaml", _make_minimal_source("s"),
                    schema_ref="../../schemas/sourcechannel.schema.json")

        results = loader._load_sources("my-target", ["s"])
        assert len(results) == 1


# ── load_target 集成 ──────────────────────────────────────────

class TestLoadTarget:
    def test_full_load_target(self, project_root):
        """完整集成测试 — 加载一个含子配置引用的 target。"""
        # schemas (宽松校验，接受所有数据)
        schemas_dir = project_root / "schemas"
        schemas_dir.mkdir(exist_ok=True)
        empty_schema = {"type": "object"}
        for name in ["targetconfig.schema.json", "sourcechannel.schema.json",
                     "filterrules.schema.json"]:
            _write_json_schema(schemas_dir / name, empty_schema)

        # target config
        targets_dir = project_root / "config" / "targets"
        targets_dir.mkdir(parents=True)
        _write_yaml(targets_dir / "my-target.yaml",
                    _make_minimal_target(target_id="my-target",
                                         source_channel_refs=["src-a", "src-b"],
                                         filter_rules_ref="config/filters/my-target/default.yaml"),
                    schema_ref="../../schemas/targetconfig.schema.json")

        # sources
        sources_dir = project_root / "config" / "sources" / "my-target"
        sources_dir.mkdir(parents=True)
        _write_yaml(sources_dir / "src-a.yaml", _make_minimal_source("src-a"),
                    schema_ref="../../schemas/sourcechannel.schema.json")
        _write_yaml(sources_dir / "src-b.yaml", _make_minimal_source("src-b"),
                    schema_ref="../../schemas/sourcechannel.schema.json")

        # filter rules
        filters_dir = project_root / "config" / "filters" / "my-target"
        filters_dir.mkdir(parents=True)
        _write_yaml(filters_dir / "default.yaml",
                    {"rules_version": 1, "target_id": "my-target",
                     "score_threshold": 60, "max_age_hours": 48, "dedup_window_hours": 72},
                    schema_ref="../../schemas/filterrules.schema.json")

        loader = ConfigLoader(project_root)
        config = loader.load_target("my-target")

        assert config.target_id == "my-target"
        assert len(config.sources) == 2
        assert config.filter_rules["score_threshold"] == 60
        assert config.classification_rules == {}
        assert config.sandbox_policy == {}

    def test_missing_target_raises(self, project_root):
        loader = ConfigLoader(project_root)
        with pytest.raises(FileNotFoundError, match="Target 配置文件不存在"):
            loader.load_target("no-such-target")

    def test_real_italy_target_loads(self):
        """验证真实的 italy target 可以通过 ConfigLoader 加载。"""
        loader = ConfigLoader(Path("."))
        config = loader.load_target("italy")
        assert config.target_id == "italy"
        assert len(config.sources) == 5
        source_ids = {s["source_id"] for s in config.sources}
        assert source_ids == {"ansa", "repubblica", "corriere", "agi", "fao-rss"}
        assert "score_threshold" in config.filter_rules
        assert "l0_domains" in config.classification_rules
        assert "command_policy" in config.sandbox_policy
