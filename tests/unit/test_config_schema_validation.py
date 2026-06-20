"""全量配置文件 Schema 校验测试。

确保所有 config/ 下的 YAML 文件通过对应 JSON Schema 校验。
未来新增配置文件也会被自动覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

from news_sentry.core.config import ConfigLoader

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas"
CONFIG_DIR = PROJECT_ROOT / "config"
NEW_PUBLIC_TARGET_IDS = {
    "spain",
    "netherlands",
    "poland",
    "israel",
    "ukraine",
    "thailand",
    "malaysia",
    "philippines",
    "nigeria",
    "egypt",
}

REMOVED_TOPIC_TARGET_IDS = {
    "africa-watch",
    "china-watch-en",
    "climate-water-food",
    "crisis-conflict",
    "critical-minerals",
    "defense-security",
    "digital-regulation",
    "energy-transition",
    "eu-policy",
    "fusion",
    "latin-america-watch",
    "middle-east-gulf",
    "migration-labor",
    "public-opinion-culture",
    "supply-chain-trade",
    "tech-ai-semiconductors",
    "us-policy",
}


def _load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _declares_schema(path: Path) -> bool:
    return "# Schema:" in path.read_text(encoding="utf-8")


# ── Declared Schema Headers ──────────────────────────────────


class TestDeclaredConfigSchemas:
    """所有声明 `# Schema:` 的 config YAML 都必须通过声明的 JSON Schema。"""

    @pytest.fixture(params=[p for p in CONFIG_DIR.glob("**/*.yaml") if _declares_schema(p)])
    def schema_declared_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_declared_schema_valid(self, schema_declared_file: Path) -> None:
        loader = ConfigLoader(PROJECT_ROOT)
        data = _load_yaml(schema_declared_file)
        loader._validate_resolved_schema(data or {}, schema_declared_file)


# ── SourceChannel ──────────────────────────────────────────────


class TestSourceChannelSchema:
    """所有 source channel YAML 通过 sourcechannel.schema.json 校验。

    排除非 sourcechannel schema 的文件：social/ 目录、_browser_fallback.yaml 等。
    """

    @pytest.fixture(
        params=[
            p
            for p in CONFIG_DIR.glob("sources/**/*.yaml")
            if "social" not in str(p)
            and "browser_fallback" not in str(p)
            and not p.name.startswith("_")
        ]
    )
    def source_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_source_channel_valid(self, source_file: Path) -> None:
        schema = _load_schema("sourcechannel.schema.json")
        data = _load_yaml(source_file)
        validate(data, schema)

    def test_source_channel_accepts_optional_language(self) -> None:
        schema = _load_schema("sourcechannel.schema.json")
        data = {
            "source_id": "test-fr",
            "display_name": "Test France",
            "type": "rss",
            "url": "https://example.com/rss.xml",
            "language": "fr",
            "credibility_base": 0.8,
            "fetch_interval_minutes": 15,
            "max_items_per_run": 20,
            "timeout_seconds": 30,
            "enabled": True,
        }

        validate(data, schema)

    def test_api_mapping_accepts_language_field_mapping(self) -> None:
        schema = _load_schema("sourcechannel.schema.json")
        data = {
            "source_id": "test-api",
            "display_name": "Test API",
            "type": "api",
            "endpoint": {"url": "https://example.com/api"},
            "api_mapping": {"items_key": "items", "language": "locale"},
            "credibility_base": 0.8,
            "fetch_interval_minutes": 15,
            "max_items_per_run": 20,
            "timeout_seconds": 30,
            "enabled": True,
        }

        validate(data, schema)


# ── TargetConfig ───────────────────────────────────────────────


class TestTargetConfigSchema:
    """所有 target YAML 通过 targetconfig.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("targets/*.yaml")))
    def target_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_target_config_valid(self, target_file: Path) -> None:
        schema = _load_schema("targetconfig.schema.json")
        data = _load_yaml(target_file)
        validate(data, schema)

    def test_public_target_network_is_region_only(self) -> None:
        targets = []
        for path in CONFIG_DIR.glob("targets/*.yaml"):
            if path.name.startswith("_"):
                continue
            data = _load_yaml(path)
            lifecycle = data.get("lifecycle") if isinstance(data, dict) else None
            if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
                continue
            targets.append(data)

        region_targets = [
            item for item in targets if item.get("region_type", item.get("monitoring_type")) in {"country", "region", "continent", "global"}
        ]
        topic_targets = [item for item in targets if item.get("monitoring_type") == "topic"]

        assert len(targets) >= 32
        assert len(region_targets) == len(targets)
        assert topic_targets == []

    def test_removed_topic_target_configs_do_not_exist(self) -> None:
        existing = {path.stem for path in CONFIG_DIR.glob("targets/*.yaml")}

        assert REMOVED_TOPIC_TARGET_IDS.isdisjoint(existing)

    def test_target_config_schema_rejects_topic_monitoring_type(self) -> None:
        schema = _load_schema("targetconfig.schema.json")
        data = {
            "target_id": "energy-transition",
            "display_name": "能源转型观察",
            "monitoring_type": "topic",
            "language_scope": {"primary": "en", "output": "zh"},
            "timezone": "Asia/Shanghai",
            "source_channel_refs": ["api/gdelt-topic"],
            "filter_rules_ref": "config/filters/energy-transition/default.yaml",
            "classification_rules_ref": "config/classification/rules-v1.yaml",
            "sandbox_profile_ref": "config/sandbox/default.yaml",
            "provider_routes_ref": "config/provider/routes.yaml",
            "output_destinations_ref": "config/output/destinations.yaml",
        }

        with pytest.raises(Exception):
            validate(data, schema)

    def test_all_public_target_source_refs_resolve(self) -> None:
        loader = ConfigLoader(PROJECT_ROOT)
        failures: list[str] = []

        for path in sorted(CONFIG_DIR.glob("targets/*.yaml")):
            if path.name.startswith("_") or path.stem == "fusion":
                continue
            data = _load_yaml(path)
            lifecycle = data.get("lifecycle") if isinstance(data, dict) else None
            if isinstance(lifecycle, dict) and lifecycle.get("status") == "archived":
                continue
            try:
                loaded = loader.load_target(path.stem)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.stem}: {exc}")
                continue
            active = [source for source in loaded.sources if source.get("enabled") is True]
            if path.stem in NEW_PUBLIC_TARGET_IDS and len(active) < 3:
                failures.append(f"{path.stem}: expected >=3 active resolved sources")

        assert failures == []

    def test_source_pool_refs_are_loaded_into_runtime_sources(self) -> None:
        loader = ConfigLoader(PROJECT_ROOT)

        config = loader.load_target("spain")

        refs = {source.get("_source_ref") for source in config.sources}
        assert "pool:global/gdelt-geopolitics" in refs
        pooled = next(source for source in config.sources if source.get("_source_ref") == "pool:global/gdelt-geopolitics")
        assert pooled["target_id"] == "spain"
        assert pooled["enabled"] is True


# ── SandboxPolicy ──────────────────────────────────────────────


class TestSandboxPolicySchema:
    """所有 sandbox YAML 通过 sandboxpolicy.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("sandbox/*.yaml")))
    def sandbox_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_sandbox_policy_valid(self, sandbox_file: Path) -> None:
        schema = _load_schema("sandboxpolicy.schema.json")
        data = _load_yaml(sandbox_file)
        validate(data, schema)


# ── FilterRules ────────────────────────────────────────────────


class TestFilterRulesSchema:
    """所有 filter rules YAML 通过 filterrules.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("filters/**/*.yaml")))
    def filter_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_filter_rules_valid(self, filter_file: Path) -> None:
        schema = _load_schema("filterrules.schema.json")
        data = _load_yaml(filter_file)
        validate(data, schema)


# ── Classification ─────────────────────────────────────────────


class TestClassificationSchema:
    """所有 classification YAML 通过 classification.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("classification/*.yaml")))
    def classification_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_classification_valid(self, classification_file: Path) -> None:
        schema = _load_schema("classification.schema.json")
        data = _load_yaml(classification_file)
        validate(data, schema)


# ── ToolManifest ───────────────────────────────────────────────


class TestToolManifestSchema:
    """所有 tool manifest YAML 通过 toolmanifest.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("toolmanifest/*.yaml")))
    def manifest_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_tool_manifest_valid(self, manifest_file: Path) -> None:
        schema = _load_schema("toolmanifest.schema.json")
        data = _load_yaml(manifest_file)
        validate(data, schema)


# ── OutputDestinations ────────────────────────────────────────


class TestOutputDestinationsSchema:
    """所有 output destinations YAML 通过 outputdestinations.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("output/*.yaml")))
    def output_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_output_destinations_valid(self, output_file: Path) -> None:
        schema = _load_schema("outputdestinations.schema.json")
        data = _load_yaml(output_file)
        validate(data, schema)


# ── SocialSource ──────────────────────────────────────────────


class TestSocialSourceSchema:
    """所有 social source YAML 通过 socialsource.schema.json 校验。"""

    @pytest.fixture(
        params=[
            p for p in CONFIG_DIR.glob("sources/**/social/**/*.yaml") if not p.name.startswith("_")
        ]
    )
    def social_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_social_source_valid(self, social_file: Path) -> None:
        schema = _load_schema("socialsource.schema.json")
        data = _load_yaml(social_file)
        validate(data, schema)


# ── MatrixGovernance ──────────────────────────────────────────


class TestMatrixGovernanceSchema:
    """所有 matrix governance YAML 通过 matrixgovernance.schema.json 校验。"""

    @pytest.fixture(params=list(CONFIG_DIR.glob("sources/**/social/_matrix_*.yaml")))
    def governance_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_matrix_governance_valid(self, governance_file: Path) -> None:
        schema = _load_schema("matrixgovernance.schema.json")
        data = _load_yaml(governance_file)
        validate(data, schema)
