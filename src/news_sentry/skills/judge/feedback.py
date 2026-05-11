"""News Sentry — Judge feedback loop for continuous improvement."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel


class JudgeFeedback(BaseModel):
    """单条人工研判反馈."""

    event_id: str
    run_id: str
    automated_confidence: int  # 0-100
    human_correct: bool
    notes: str = ""
    created_at: str = ""

    def model_post_init(self, __context: object) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


class FeedbackStore:
    """管理研判反馈的持久化与统计."""

    def __init__(self, memory_dir: Path) -> None:
        self.file_path = memory_dir / "judge_feedback.jsonl"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, feedback: JudgeFeedback) -> None:
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(feedback.model_dump_json() + "\n")

    def load_all(self) -> list[JudgeFeedback]:
        if not self.file_path.is_file():
            return []
        records: list[JudgeFeedback] = []
        for line in self.file_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(JudgeFeedback(**json.loads(line)))
        return records

    def stats(self) -> dict[str, float]:
        records = self.load_all()
        if not records:
            return {"total": 0, "correct": 0, "accuracy": 0.0}
        correct = sum(1 for r in records if r.human_correct)
        return {
            "total": len(records),
            "correct": correct,
            "accuracy": correct / len(records),
        }
