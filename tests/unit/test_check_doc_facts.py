"""tools/check_doc_facts.py 的单元测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
_SPEC = importlib.util.spec_from_file_location("check_doc_facts", _TOOLS_DIR / "check_doc_facts.py")
assert _SPEC is not None and _SPEC.loader is not None
cdf = importlib.util.module_from_spec(_SPEC)
# 必须先注册到 sys.modules，否则模块内 @dataclass 解析 __module__ 会失败
sys.modules[_SPEC.name] = cdf
_SPEC.loader.exec_module(cdf)


def _rule_by_label(label_sub: str):
    matches = [r for r in cdf.ALL_RULES if label_sub in r.label]
    assert len(matches) == 1, f"expected exactly one rule for {label_sub!r}, got {len(matches)}"
    return matches[0]


class TestCountRuleExtraction:
    def test_schema_count_cjk(self) -> None:
        rule = _rule_by_label("JSON Schema")
        match = rule.pattern.search("契约目录共 19 份 JSON Schema 文件")
        assert match is not None
        assert cdf._to_int(match.group(1)) == 19

    def test_schema_count_english_plural(self) -> None:
        rule = _rule_by_label("JSON Schema")
        match = rule.pattern.search("Validated against 13 JSON Schemas at load time")
        assert match is not None
        assert cdf._to_int(match.group(1)) == 13

    def test_target_count_cjk(self) -> None:
        rule = _rule_by_label("target 总数（中文）")
        match = rule.pattern.search("- **监控目标**：81 个已配置 target（italy、japan 等）")
        assert match is not None
        assert cdf._to_int(match.group(1)) == 81

    def test_target_count_english(self) -> None:
        rule = _rule_by_label("target 总数（英文）")
        text = "the full configuration has **81 targets** spanning global regions"
        match = rule.pattern.search(text)
        assert match is not None
        assert cdf._to_int(match.group(1)) == 81

    def test_source_count_cjk(self) -> None:
        rule = _rule_by_label("信源文件数（中文）")
        match = rule.pattern.search("- **信源规模**：244 源，覆盖 81 个 target")
        assert match is not None
        assert cdf._to_int(match.group(1)) == 244

    def test_comma_number(self) -> None:
        rule = _rule_by_label("source 文件数（英文）")
        match = rule.pattern.search("The repo ships 1,128 sources across targets")
        assert match is not None
        assert cdf._to_int(match.group(1)) == 1128


class TestFalsePositiveGuards:
    def test_code_span_path_not_matched(self) -> None:
        line = cdf._INLINE_CODE_RE.sub("", "实时清单见 `config/targets/` 目录")
        for rule in cdf.COUNT_RULES:
            assert rule.pattern.search(line) is None

    def test_fenced_block_skipped(self) -> None:
        text = "```yaml\n81 个已配置 target\n```\n正文无声明\n"
        findings = list(cdf.iter_claim_lines(text))
        assert all("81" not in stripped for _, stripped in findings)

    def test_version_string_not_matched_as_count(self) -> None:
        for rule in cdf.COUNT_RULES:
            assert rule.pattern.search("升级到 v2.0.0-rc3 版本") is None


class TestForbiddenRules:
    def test_hardcoded_total_tests_flagged(self) -> None:
        rule = _rule_by_label("总测试数硬编码")
        assert rule.pattern.search("pytest - 3,020 tests pass") is not None
        assert rule.pattern.search("3020 tests collected") is not None

    def test_test_badge_flagged(self) -> None:
        rule = _rule_by_label("测试数徽章")
        assert rule.pattern.search("badge/tests-3020%20passed") is not None

    def test_rc_version_flagged(self) -> None:
        rule = _rule_by_label("rc 版本号")
        assert rule.pattern.search("**Tag:** v2.0.0-rc3") is not None

    def test_legitimate_content_not_flagged(self) -> None:
        for rule in cdf.FORBIDDEN_RULES:
            assert rule.pattern.search("质量门禁见 docs/status.md") is None
            assert rule.pattern.search("15 分钟 Cron 采集推进") is None


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Path:
    root = tmp_path
    (root / "schemas").mkdir()
    for i in range(2):
        (root / "schemas" / f"s{i}.schema.json").write_text("{}", encoding="utf-8")
    targets = root / "config" / "targets"
    targets.mkdir(parents=True)
    (targets / "_template.yaml").write_text("template: true", encoding="utf-8")
    for name in ("italy", "japan"):
        (targets / f"{name}.yaml").write_text("target: true", encoding="utf-8")
    sources = root / "config" / "sources" / "italy"
    sources.mkdir(parents=True)
    (sources / "ansa.yaml").write_text("source: true", encoding="utf-8")
    return root


class TestEndToEnd:
    def test_consistent_docs_pass(
        self, mini_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (mini_repo / "README.md").write_text(
            "# Demo\n\n共 2 份 JSON Schema；**2 个已配置 target**；1 源。\n",
            encoding="utf-8",
        )
        code = cdf.main(["--root", str(mini_repo)])
        output = capsys.readouterr().out
        assert code == 0
        assert "[OK]" in output

    def test_mismatched_claim_fails(
        self, mini_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (mini_repo / "README.md").write_text(
            "# Demo\n\n共 9 份 JSON Schema。\n",
            encoding="utf-8",
        )
        code = cdf.main(["--root", str(mini_repo)])
        output = capsys.readouterr().out
        assert code == 1
        assert "[FAIL]" in output
        assert "claim=9 actual=2" in output

    def test_forbidden_claim_fails_even_if_accurate(
        self, mini_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (mini_repo / "README.md").write_text(
            "# Demo\n\npytest - 3,020 tests pass\n",
            encoding="utf-8",
        )
        code = cdf.main(["--root", str(mini_repo)])
        output = capsys.readouterr().out
        assert code == 1
        assert "总测试数硬编码" in output

    def test_missing_scan_file_warns_but_passes(
        self, mini_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 只提供 README.md，其余扫描目标缺失 → 警告但不失败
        (mini_repo / "README.md").write_text("# Demo\n\n干净文档，无数字声明。\n", encoding="utf-8")
        code = cdf.main(["--root", str(mini_repo)])
        output = capsys.readouterr().out
        assert code == 0
        assert "跳过不存在的扫描目标" in output
