"""Tests for cli/doctor.py — 项目健康检查."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from news_sentry.cli.doctor import (
    _AI_KEY_VARS,
    DoctorReport,
    _count_eval_coverage,
    _extract_glossary_terms,
    doctor_command,
    run_doctor,
)

# ──────────────────────────────────────────────────
# DoctorReport model
# ──────────────────────────────────────────────────


class TestDoctorReport:
    def test_all_passed_when_all_checks_pass(self):
        report = DoctorReport(
            schema_check={"passed": True, "details": ["ok"]},
            directory_check={"passed": True, "details": ["ok"]},
            source_check={"passed": True, "details": ["ok"]},
            provider_check={"passed": True, "details": ["ok"]},
            browser_bridge_check={"passed": True, "details": ["ok"]},
            session_profiles_check={"passed": True, "details": ["ok"]},
            glossary_check={"passed": True, "details": ["ok"]},
        )
        assert report.all_passed is True

    def test_all_passed_fails_when_one_check_fails(self):
        report = DoctorReport(
            schema_check={"passed": False, "details": ["missing"]},
            directory_check={"passed": True, "details": ["ok"]},
            source_check={"passed": True, "details": ["ok"]},
            provider_check={"passed": True, "details": ["ok"]},
            browser_bridge_check={"passed": True, "details": ["ok"]},
            session_profiles_check={"passed": True, "details": ["ok"]},
            glossary_check={"passed": True, "details": ["ok"]},
        )
        assert report.all_passed is False

    def test_all_passed_with_empty_checks(self):
        report = DoctorReport()
        # Empty dicts are falsy — generator yields nothing, all() returns True
        assert report.all_passed is True

    def test_to_dict_keys(self):
        report = DoctorReport()
        d = report.to_dict()
        assert set(d.keys()) == {
            "schema_check",
            "directory_check",
            "source_check",
            "provider_check",
            "browser_bridge_check",
            "session_profiles_check",
            "glossary_check",
            "overall",
        }

    def test_to_dict_overall_pass(self):
        report = DoctorReport(
            schema_check={"passed": True, "details": []},
            directory_check={"passed": True, "details": []},
            source_check={"passed": True, "details": []},
            provider_check={"passed": True, "details": []},
            browser_bridge_check={"passed": True, "details": []},
            session_profiles_check={"passed": True, "details": []},
            glossary_check={"passed": True, "details": []},
        )
        assert report.to_dict()["overall"] == "PASS"

    def test_to_dict_overall_fail(self):
        report = DoctorReport(
            schema_check={"passed": False, "details": []},
        )
        assert report.to_dict()["overall"] == "FAIL"


# ──────────────────────────────────────────────────
# run_doctor
# ──────────────────────────────────────────────────


class TestRunDoctorSchemaCheck:
    def test_schemas_directory_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a fake schemas/ dir with 3 json files
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        for i in range(3):
            (schemas_dir / f"schema_{i}.json").write_text("{}")

        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.schema_check["passed"] is True
        assert "3 schema files found" in report.schema_check["details"][0]

    def test_schemas_directory_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.schema_check["passed"] is False
        assert any("missing" in d.lower() for d in report.schema_check["details"])


class TestRunDoctorDirectoryCheck:
    def test_all_dirs_exist(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        data_path = tmp_path / "data" / "italy"
        from news_sentry.cli.doctor import REQUIRED_DIRS

        for d in REQUIRED_DIRS:
            (data_path / d).mkdir(parents=True)

        monkeypatch.chdir(tmp_path)
        report = run_doctor("italy", data_root=str(tmp_path / "data"))
        assert report.directory_check["passed"] is True
        for d in REQUIRED_DIRS:
            assert any(f"{d}/ exists" in detail for detail in report.directory_check["details"])

    def test_missing_dirs_cause_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        data_path = tmp_path / "data" / "italy"
        data_path.mkdir(parents=True)  # only base dir, no subdirs

        monkeypatch.chdir(tmp_path)
        report = run_doctor("italy", data_root=str(tmp_path / "data"))
        assert report.directory_check["passed"] is False
        assert any("MISSING" in d for d in report.directory_check["details"])


class TestRunDoctorProviderCheck:
    def test_no_provider_keys_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        for var in _AI_KEY_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.provider_check["passed"] is False
        assert any("not set" in d for d in report.provider_check["details"])

    def test_single_provider_key_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Clear all, then set one
        for var in _AI_KEY_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.provider_check["passed"] is True
        details = report.provider_check["details"]
        assert any("GEMINI_API_KEY is set" in d for d in details)
        assert any("DEEPSEEK_API_KEY not set" in d for d in details)
        assert any("GROQ_API_KEY not set" in d for d in details)

    def test_all_provider_keys_set(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("GEMINI_API_KEY", "key1")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "key2")
        monkeypatch.setenv("GROQ_API_KEY", "key3")
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.provider_check["passed"] is True
        for var in _AI_KEY_VARS:
            assert any(f"{var} is set" in d for d in report.provider_check["details"])


class TestRunDoctorSourceCheck:
    def test_source_check_placeholder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.source_check["passed"] is True
        assert any("network" in d for d in report.source_check["details"])


class TestRunDoctorBrowserBridgeCheck:
    def test_browser_bridge_v2_placeholder(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.browser_bridge_check["passed"] is True
        assert any("rss-bridge" in d.lower() for d in report.browser_bridge_check["details"])


class TestRunDoctorSessionProfilesCheck:
    def test_session_dir_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.session_profiles_check["passed"] is False
        assert any("not found" in d for d in report.session_profiles_check["details"])

    def test_session_dir_exists_with_yamls(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        session_dir = tmp_path / "config" / "session-profiles" / "italy"
        session_dir.mkdir(parents=True)
        (session_dir / "test.yaml").write_text("{}")
        (session_dir / "test2.yaml").write_text("{}")

        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.session_profiles_check["passed"] is True
        assert any("2 session configs" in d for d in report.session_profiles_check["details"])


class TestRunDoctorGlossaryCheck:
    def test_glossary_file_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.glossary_check["passed"] is False
        assert any("not found" in d for d in report.glossary_check["details"])

    def test_glossary_parses_terms(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        glossary_path = tmp_path / "docs" / "it-zh-glossary.md"
        glossary_path.parent.mkdir(parents=True)
        glossary_path.write_text(
            """\
| 意大利语 | 中文 | 分类 |
|----------|------|------|
| governo | 政府 | 政治 |
| crisi | 危机 | 通用 |
| elezioni | 选举 | 政治 |
"""
        )

        monkeypatch.chdir(tmp_path)
        report = run_doctor("test-target", data_root=str(tmp_path / "data"))
        assert report.glossary_check["passed"] is True
        assert any("3 glossary terms" in d for d in report.glossary_check["details"])
        # No eval files, so coverage is skipped
        assert any("no eval-set files" in d for d in report.glossary_check["details"])


# ──────────────────────────────────────────────────
# _extract_glossary_terms
# ──────────────────────────────────────────────────


class TestExtractGlossaryTerms:
    def test_extracts_italian_terms(self, tmp_path: Path):
        glossary = tmp_path / "glossary.md"
        glossary.write_text(
            """\
| 意大利语 | 中文 | 分类 |
|----------|------|------|
| governo | 政府 | 政治 |
| crisi | 危机 | 通用 |
| elezioni | 选举 | 政治 |
"""
        )
        terms = _extract_glossary_terms(glossary)
        assert terms == {"governo", "crisi", "elezioni"}

    def test_skips_header_and_separator_rows(self, tmp_path: Path):
        glossary = tmp_path / "glossary.md"
        glossary.write_text(
            """\
| 意大利语 | 中文 |
|----------|------|
| test | 测试 |
"""
        )
        terms = _extract_glossary_terms(glossary)
        assert terms == {"test"}
        assert "italiano" not in {t.lower() for t in terms}
        assert "意大利语" not in terms

    def test_lowercases_terms(self, tmp_path: Path):
        glossary = tmp_path / "glossary.md"
        glossary.write_text(
            """\
| 意大利语 | 中文 |
|----------|------|
| Governo | 政府 |
"""
        )
        terms = _extract_glossary_terms(glossary)
        assert "governo" in terms

    def test_handles_empty_file(self, tmp_path: Path):
        glossary = tmp_path / "glossary.md"
        glossary.write_text("")
        terms = _extract_glossary_terms(glossary)
        assert terms == set()

    def test_stops_at_table_end(self, tmp_path: Path):
        glossary = tmp_path / "glossary.md"
        glossary.write_text(
            """\
| 意大利语 | 中文 |
|----------|------|
| term1 | 术语1 |

This is not a table anymore.
| not | a | term |
"""
        )
        terms = _extract_glossary_terms(glossary)
        assert terms == {"term1"}


# ──────────────────────────────────────────────────
# _count_eval_coverage
# ──────────────────────────────────────────────────


class TestCountEvalCoverage:
    def test_full_coverage(self, tmp_path: Path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(
            json.dumps(
                {
                    "examples": [
                        {"input": {"title_original": "governo crisi", "content_original": "test"}},
                        {"input": {"title_original": "elezioni 2026", "content_original": ""}},
                    ]
                }
            )
        )
        glossary_terms = {"governo", "crisi", "elezioni"}
        total, covered = _count_eval_coverage(eval_path, glossary_terms)
        assert total == 2
        assert covered == 2

    def test_partial_coverage(self, tmp_path: Path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(
            json.dumps(
                {
                    "examples": [
                        {"input": {"title_original": "governo", "content_original": "test"}},
                        {"input": {"title": "nothing matches here", "content": "nope"}},
                    ]
                }
            )
        )
        glossary_terms = {"governo"}
        total, covered = _count_eval_coverage(eval_path, glossary_terms)
        assert total == 2
        assert covered == 1

    def test_no_coverage(self, tmp_path: Path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(
            json.dumps(
                {
                    "examples": [
                        {"input": {"title_original": "abc", "content_original": "def"}},
                    ]
                }
            )
        )
        glossary_terms = {"governo"}
        total, covered = _count_eval_coverage(eval_path, glossary_terms)
        assert total == 1
        assert covered == 0

    def test_empty_examples(self, tmp_path: Path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(json.dumps({"examples": []}))
        total, covered = _count_eval_coverage(eval_path, {"governo"})
        assert total == 0
        assert covered == 0

    def test_searches_all_text_fields(self, tmp_path: Path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(
            json.dumps(
                {
                    "examples": [
                        {
                            "input": {
                                "title_original": "",
                                "content_original": "",
                                "title": "",
                                "content": "",
                                "source_id": "governo-source",
                            }
                        },
                    ]
                }
            )
        )
        glossary_terms = {"governo"}
        total, covered = _count_eval_coverage(eval_path, glossary_terms)
        assert covered == 1


# ──────────────────────────────────────────────────
# doctor_command
# ──────────────────────────────────────────────────


class TestDoctorCommand:
    def test_json_output_pass(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        # Create minimal passing state
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "test.json").write_text("{}")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        exit_code = doctor_command(
            "test-target", data_root=str(tmp_path / "data"), json_output=True
        )
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["overall"] in ("PASS", "FAIL")
        assert "schema_check" in output
        assert "directory_check" in output
        assert "provider_check" in output
        # With GEMINI_API_KEY and schemas/, overall should be PASS
        # (session_profiles and glossary will fail, so overall is FAIL)
        assert exit_code != 0

    def test_text_output_format(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        (schemas_dir / "test.json").write_text("{}")

        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        _ = doctor_command("test-target", data_root=str(tmp_path / "data"), json_output=False)
        captured = capsys.readouterr()
        assert "Doctor check:" in captured.out
        assert "[PASS]" in captured.out or "[FAIL]" in captured.out


# ──────────────────────────────────────────────────
# _AI_KEY_VARS constant
# ──────────────────────────────────────────────────


class TestAIKeyVars:
    def test_contains_all_three_providers(self):
        assert "GEMINI_API_KEY" in _AI_KEY_VARS
        assert "DEEPSEEK_API_KEY" in _AI_KEY_VARS
        assert "GROQ_API_KEY" in _AI_KEY_VARS

    def test_is_tuple(self):
        assert isinstance(_AI_KEY_VARS, tuple)

    def test_no_legacy_keys(self):
        assert "FREELLMAPI_API_KEY" not in _AI_KEY_VARS
        assert "OPENAI_API_KEY" not in _AI_KEY_VARS
