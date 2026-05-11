from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.cli.doctor import DoctorReport, doctor_command, run_doctor


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
        for d in ["raw", "evaluated", "drafts", "reviewed", "published",
                   "archive", "memory", "logs"]:
            (data_path / d).mkdir(parents=True)
        report = run_doctor("test-target", data_root=tmp)
        assert report.directory_check["passed"] is True


def test_doctor_command_json_output(capsys):
    """JSON 输出模式。"""
    with TemporaryDirectory() as tmp:
        data_path = Path(tmp) / "test-target"
        for d in ["raw", "evaluated", "drafts", "reviewed", "published",
                   "archive", "memory", "logs"]:
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
