import json
from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.cli.doctor import (
    DoctorReport,
    _count_eval_coverage,
    _extract_glossary_terms,
    doctor_command,
    run_doctor,
)


def test_doctor_report_structure():
    report = DoctorReport(
        schema_check={"passed": True, "details": ["13/13 schemas valid"]},
        directory_check={"passed": True, "details": ["all dirs present"]},
        source_check={"passed": True, "details": ["3/3 sources reachable"]},
        provider_check={"passed": False, "details": ["ANTHROPIC_API_KEY not set"]},
    )
    assert report.schema_check["passed"] is True
    assert report.provider_check["passed"] is False
    assert not report.all_passed
    assert report.to_dict()["overall"] == "FAIL"


def test_doctor_report_all_pass():
    report = DoctorReport(
        schema_check={"passed": True, "details": []},
        directory_check={"passed": True, "details": []},
        source_check={"passed": True, "details": []},
        provider_check={"passed": True, "details": []},
    )
    assert report.all_passed
    assert report.to_dict()["overall"] == "PASS"


def test_run_doctor_missing_dirs():
    """缺少数据目录时应报告失败。"""
    with TemporaryDirectory() as tmp:
        report = run_doctor("test-target", data_root=tmp)
        assert report.directory_check["passed"] is False
        assert any("MISSING" in d for d in report.directory_check["details"])


def test_run_doctor_existing_dirs():
    """存在所有数据目录时应通过。"""
    with TemporaryDirectory() as tmp:
        data_path = Path(tmp) / "test-target"
        for d in [
            "raw",
            "evaluated",
            "drafts",
            "reviewed",
            "published",
            "archive",
            "memory",
            "logs",
        ]:
            (data_path / d).mkdir(parents=True)
        report = run_doctor("test-target", data_root=tmp)
        assert report.directory_check["passed"] is True


def test_run_doctor_provider_check_accepts_openrouter_key(monkeypatch):
    """默认 OpenRouter Key 存在时 provider_check 应通过。"""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    with TemporaryDirectory() as tmp:
        report = run_doctor("test-target", data_root=tmp)

    assert report.provider_check["passed"] is True
    assert any("OPENROUTER_API_KEY is set" in d for d in report.provider_check["details"])


def test_doctor_command_json_output(capsys):
    """JSON 输出模式。"""
    with TemporaryDirectory() as tmp:
        data_path = Path(tmp) / "test-target"
        for d in [
            "raw",
            "evaluated",
            "drafts",
            "reviewed",
            "published",
            "archive",
            "memory",
            "logs",
        ]:
            (data_path / d).mkdir(parents=True)
        exit_code = doctor_command("test-target", data_root=tmp, json_output=True)
        captured = capsys.readouterr()
        assert '"overall"' in captured.out
        assert exit_code in (0, 1)


def test_doctor_command_text_output(capsys):
    """文本输出模式。"""
    with TemporaryDirectory() as tmp:
        exit_code = doctor_command("test-target", data_root=tmp, json_output=False)
        captured = capsys.readouterr()
        assert "Doctor check:" in captured.out
        assert exit_code in (0, 1)


def test_extract_glossary_terms(tmp_path: Path):
    """术语表解析应提取意大利语词条。"""
    glossary = tmp_path / "glossary.md"
    glossary.write_text(
        "## 表 1：政府机构\n\n"
        "| 意大利语 | 中文规范译名 | 缩写/别名 | 说明 | 更新日期 |\n"
        "|---------|------------|---------|------|---------|\n"
        "| Ministero degli Affari Esteri | 外交部 | MAE | 外交 | 2026-01-01 |\n"
        "| Senato | 参议院 | — | 上议院 | 2026-01-01 |\n",
        encoding="utf-8",
    )
    terms = _extract_glossary_terms(glossary)
    assert "ministero degli affari esteri" in terms
    assert "senato" in terms
    assert len(terms) == 2


def test_extract_glossary_terms_no_table(tmp_path: Path):
    """无表格时应返回空集合。"""
    glossary = tmp_path / "glossary.md"
    glossary.write_text("# Empty glossary\n\nNo tables here.\n", encoding="utf-8")
    terms = _extract_glossary_terms(glossary)
    assert terms == set()


def test_count_eval_coverage(tmp_path: Path):
    """评估集覆盖率统计。"""
    eval_data = {
        "examples": [
            {
                "input": {
                    "title_original": "Senato approva riforma",
                    "content_original": "Il Senato ha approvato",
                    "source_id": "ansa",
                    "language": "it",
                },
            },
            {
                "input": {
                    "title_original": "Weather forecast",
                    "content_original": "Sunny day",
                    "source_id": "weather",
                    "language": "en",
                },
            },
        ]
    }
    eval_file = tmp_path / "eval-set-v1.json"
    eval_file.write_text(json.dumps(eval_data), encoding="utf-8")

    terms = {"senato", "ministero"}
    total, covered = _count_eval_coverage(eval_file, terms)
    assert total == 2
    assert covered == 1


def test_glossary_check_in_report():
    """DoctorReport 应包含 glossary_check 字段。"""
    report = DoctorReport(glossary_check={"passed": True, "details": ["86 terms"]})
    assert report.glossary_check["passed"] is True
    d = report.to_dict()
    assert "glossary_check" in d
