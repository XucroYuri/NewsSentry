from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


TOP20_COUNTRY_TARGETS_EX_CHINA = {
    "united-states",
    "united-kingdom",
    "germany",
    "france",
    "russia",
    "japan",
    "india",
    "south-korea",
    "italy",
    "canada",
    "australia",
    "brazil",
    "mexico",
    "indonesia",
    "turkey",
    "saudi-arabia",
    "united-arab-emirates",
    "south-africa",
    "vietnam",
    "singapore",
}

VNEXT_TOPIC_TARGETS = {
    "china-watch-en",
    "us-policy",
    "eu-policy",
    "africa-watch",
    "latin-america-watch",
    "tech-ai-semiconductors",
    "energy-transition",
    "crisis-conflict",
    "supply-chain-trade",
    "climate-water-food",
    "public-opinion-culture",
}


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def test_vnext_country_targets_cover_top20_excluding_china() -> None:
    for target_id in sorted(TOP20_COUNTRY_TARGETS_EX_CHINA):
        target_path = PROJECT_ROOT / "config" / "targets" / f"{target_id}.yaml"
        assert target_path.is_file(), f"missing target config: {target_id}"
        target = _load_yaml(target_path)
        assert target.get("monitoring_type") == "country"
        refs = [str(ref) for ref in target.get("source_channel_refs", [])]
        assert refs, f"{target_id} has no source refs"
        for ref in refs:
            source_path = PROJECT_ROOT / "config" / "sources" / target_id / f"{ref}.yaml"
            assert source_path.is_file(), f"missing source config: {target_id}/{ref}"


def test_vnext_topic_targets_have_public_source_basis() -> None:
    for target_id in sorted(VNEXT_TOPIC_TARGETS):
        target_path = PROJECT_ROOT / "config" / "targets" / f"{target_id}.yaml"
        assert target_path.is_file(), f"missing topic target config: {target_id}"
        target = _load_yaml(target_path)
        assert target.get("monitoring_type") == "topic"
        refs = [str(ref) for ref in target.get("source_channel_refs", [])]
        assert refs, f"{target_id} has no source refs"
        source_count = 0
        for ref in refs:
            source_path = PROJECT_ROOT / "config" / "sources" / target_id / f"{ref}.yaml"
            if source_path.is_file():
                source_count += 1
        assert source_count >= 1, f"{target_id} has no loadable source configs"
