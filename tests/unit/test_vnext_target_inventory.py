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

ADDED_ECONOMY_REGION_TARGETS = {
    "argentina",
    "switzerland",
    "belgium",
    "sweden",
    "austria",
    "norway",
    "denmark",
    "finland",
    "portugal",
    "greece",
    "czechia",
    "romania",
    "hungary",
    "chile",
    "colombia",
    "peru",
    "pakistan",
    "bangladesh",
    "qatar",
    "kuwait",
    "iraq",
    "iran",
    "morocco",
    "kenya",
    "ethiopia",
    "algeria",
}

ADDED_AGGREGATE_REGION_TARGETS = {
    "global",
    "europe",
    "european-union",
    "africa",
    "african-union",
    "middle-east",
    "latin-america",
    "asia-pacific",
    "east-asia",
    "southeast-asia",
    "south-asia",
    "central-asia",
    "nordics",
    "international-organizations",
    "un-system",
    "imf-world-bank",
    "trade-wto-oecd",
    "energy-opec-iea",
    "security-nato-osce",
    "g7",
    "g20",
    "brics",
    "asean",
}

RETIRED_TOPIC_TARGETS = {
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


def _load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _source_ref_exists(target_id: str, ref: str) -> bool:
    if ref.startswith("pool:"):
        pool_ref = ref.removeprefix("pool:")
        return (PROJECT_ROOT / "config" / "source-pools" / f"{pool_ref}.yaml").is_file()
    return (PROJECT_ROOT / "config" / "sources" / target_id / f"{ref}.yaml").is_file()


def _target_configs() -> dict[str, dict]:
    target_dir = PROJECT_ROOT / "config" / "targets"
    return {
        path.stem: _load_yaml(path)
        for path in sorted(target_dir.glob("*.yaml"))
        if path.stem != "_template"
    }


def test_vnext_country_targets_cover_top20_excluding_china() -> None:
    for target_id in sorted(TOP20_COUNTRY_TARGETS_EX_CHINA):
        target_path = PROJECT_ROOT / "config" / "targets" / f"{target_id}.yaml"
        assert target_path.is_file(), f"missing target config: {target_id}"
        target = _load_yaml(target_path)
        assert target.get("monitoring_type") == "country"
        assert target.get("region_type") == "country"
        refs = [str(ref) for ref in target.get("source_channel_refs", [])]
        assert refs, f"{target_id} has no source refs"
        for ref in refs:
            assert _source_ref_exists(target_id, ref), f"missing source config: {target_id}/{ref}"


def test_vnext_global_region_network_is_configured() -> None:
    targets = _target_configs()

    missing_economies = ADDED_ECONOMY_REGION_TARGETS - set(targets)
    missing_aggregates = ADDED_AGGREGATE_REGION_TARGETS - set(targets)
    assert not missing_economies, f"missing economy region targets: {sorted(missing_economies)}"
    assert not missing_aggregates, f"missing aggregate region targets: {sorted(missing_aggregates)}"

    country_targets = {
        target_id
        for target_id, target in targets.items()
        if target.get("region_type") == "country"
    }
    aggregate_targets = {
        target_id
        for target_id, target in targets.items()
        if target.get("region_type") in {"region", "continent", "global"}
    }

    assert len(country_targets) >= 58
    assert len(aggregate_targets) >= 20
    assert "china" not in targets


def test_new_region_targets_have_resolvable_active_sources() -> None:
    targets = _target_configs()
    required_targets = ADDED_ECONOMY_REGION_TARGETS | ADDED_AGGREGATE_REGION_TARGETS

    for target_id in sorted(required_targets):
        refs = [str(ref) for ref in targets[target_id].get("source_channel_refs", [])]
        assert len(refs) >= 3, f"{target_id} should have at least 3 active source refs"
        for ref in refs:
            assert _source_ref_exists(target_id, ref), f"missing source config: {target_id}/{ref}"


def test_vnext_topic_targets_are_retired_from_config() -> None:
    for target_id in sorted(RETIRED_TOPIC_TARGETS):
        target_path = PROJECT_ROOT / "config" / "targets" / f"{target_id}.yaml"
        source_path = PROJECT_ROOT / "config" / "sources" / target_id
        filter_path = PROJECT_ROOT / "config" / "filters" / target_id
        assert not target_path.exists(), f"retired topic target still exists: {target_id}"
        assert not source_path.exists(), f"retired topic sources still exist: {target_id}"
        assert not filter_path.exists(), f"retired topic filters still exist: {target_id}"


def test_all_public_target_configs_are_regions() -> None:
    target_dir = PROJECT_ROOT / "config" / "targets"
    for target_path in sorted(target_dir.glob("*.yaml")):
        target = _load_yaml(target_path)
        assert target.get("monitoring_type") in {"country", "region", "continent", "global"}
        assert target.get("region_type") in {"country", "region", "continent", "global"}
        assert "topic_label" not in target
