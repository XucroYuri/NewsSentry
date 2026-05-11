from news_sentry.cli.doctor import DoctorReport


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
