import json
from pathlib import Path
from tempfile import TemporaryDirectory

from news_sentry.core.metrics import MetricsWriter, RunMetrics


def test_metrics_to_jsonl():
    m = RunMetrics(
        run_id="r-001",
        target_id="italy",
        collected=10,
        filtered=8,
        judged=5,
        outputted=3,
        duration_collect_ms=1500,
        duration_filter_ms=200,
        duration_judge_ms=5000,
        duration_output_ms=100,
        provider_calls={"openai": 3, "anthropic": 2},
        provider_cost={"openai": 0.015, "anthropic": 0.008},
    )
    assert m.collected == 10
    assert m.provider_calls["openai"] == 3


def test_metrics_writer_append_jsonl():
    with TemporaryDirectory() as tmp:
        writer = MetricsWriter(Path(tmp))
        m = RunMetrics(
            run_id="r-001", target_id="italy",
            collected=5, filtered=3, judged=2, outputted=1,
            duration_collect_ms=100, duration_filter_ms=100,
            duration_judge_ms=100, duration_output_ms=100,
            provider_calls={}, provider_cost={},
        )
        writer.write(m)
        written = list(Path(tmp).glob("*.jsonl"))
        assert len(written) == 1
        line = written[0].read_text().strip()
        data = json.loads(line)
        assert data["run_id"] == "r-001"
