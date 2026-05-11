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

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = PROJECT_ROOT / "schemas"
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── SourceChannel ──────────────────────────────────────────────


class TestSourceChannelSchema:
    """所有 source channel YAML 通过 sourcechannel.schema.json 校验。

    排除非 sourcechannel schema 的文件：social/ 目录、_browser_fallback.yaml 等。
    """

    @pytest.fixture(params=[
        p for p in CONFIG_DIR.glob("sources/**/*.yaml")
        if "social" not in str(p)
        and "browser_fallback" not in str(p)
        and not p.name.startswith("_template")
    ])
    def source_file(self, request: pytest.FixtureRequest) -> Path:
        return request.param

    def test_source_channel_valid(self, source_file: Path) -> None:
        schema = _load_schema("sourcechannel.schema.json")
        data = _load_yaml(source_file)
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

    @pytest.fixture(params=[
        p for p in CONFIG_DIR.glob("sources/**/social/**/*.yaml")
        if not p.name.startswith("_")
    ])
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
