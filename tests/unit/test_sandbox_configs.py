from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import validate

SCHEMA_PATH = Path(__file__).parent.parent.parent / "schemas" / "sandboxpolicy.schema.json"
SANDBOX_DIR = Path(__file__).parent.parent.parent / "config" / "sandbox"

with open(SCHEMA_PATH, encoding="utf-8") as f:
    SCHEMA = json.load(f)

SANDBOX_YAMLS = [
    "default.yaml",
    "local-workstation.yaml",
    "cloud-vps.yaml",
    "full.yaml",
]


class TestSandboxConfigSchema:
    @pytest.mark.parametrize("yaml_name", SANDBOX_YAMLS)
    def test_sandbox_yaml_valid(self, yaml_name: str) -> None:
        yaml_path = SANDBOX_DIR / yaml_name
        with open(yaml_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        # Should not raise
        validate(instance=config, schema=SCHEMA)
