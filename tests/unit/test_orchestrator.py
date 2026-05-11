from news_sentry.core.orchestrator import OrchestratorMode, PipelineOrchestrator


def test_sequential_mode_is_default():
    orch = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
    assert orch.mode == OrchestratorMode.SEQUENTIAL


def test_concurrent_mode_accepts_parallelism():
    orch = PipelineOrchestrator(mode=OrchestratorMode.CONCURRENT, parallelism=3)
    assert orch.mode == OrchestratorMode.CONCURRENT
    assert orch.parallelism == 3


def test_orchestrator_validate_stages_sequential():
    orch = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
    stages = ["collect", "filter", "judge", "output"]
    valid = orch.validate_stage_order(stages)
    assert valid is True


def test_orchestrator_validate_stages_invalid():
    orch = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
    stages = ["judge", "collect"]  # wrong order
    valid = orch.validate_stage_order(stages)
    assert valid is False


def test_orchestrator_stage_registry():
    orch = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
    assert "collect" in orch.known_stages
    assert "filter" in orch.known_stages
    assert "judge" in orch.known_stages
    assert "output" in orch.known_stages


def test_unknown_stage_fails_validation():
    orch = PipelineOrchestrator(mode=OrchestratorMode.SEQUENTIAL)
    assert orch.validate_stage_order(["collect", "nonexistent"]) is False
