import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.agents.agent_input import AgentInput
from app.agents.forensics_agent import ForensicsAgent
from app.agents.rev_agent import RevAgent
from app.challenge.challenge_input import ChallengeInput
from app.client.base_client import BaseAIClient
from app.external_tools import (
    TARGET_PATH_METADATA_KEY,
    AllowedTool,
    BinwalkTool,
    ExifTool,
    ExternalProcessResult,
    ExternalProcessStatus,
    ExternalToolInvocation,
    ExternalToolRegistry,
    ExternalToolRequestBuilder,
    ExternalToolStatus,
    ExternalToolType,
    FileTool,
    NmTool,
    ObjdumpTool,
    ReadelfTool,
    StringsTool,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolPolicyDecision,
    ToolRequest,
)
from app.iteration import (
    ExternalToolEvidenceFormatter,
    ExternalToolIterationCoordinator,
    ExternalToolIterationStatus,
    IterationAction,
    IterationActionStatus,
    IterationActionType,
    IterationBudget,
    IterationBudgetManager,
    IterationOrchestrator,
    IterationRunContext,
    IterationStateManager,
    IterationStopEvaluator,
    IterationUsage,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)
TOOL_CASES = (
    (StringsTool, ExternalToolType.STRINGS, ()),
    (FileTool, ExternalToolType.FILE, ()),
    (ExifTool, ExternalToolType.EXIFTOOL, ("-j",)),
    (ReadelfTool, ExternalToolType.READELF, ("-W", "-h", "-l", "-S", "-s")),
    (ObjdumpTool, ExternalToolType.OBJDUMP, ("-d", "-f", "-h")),
    (NmTool, ExternalToolType.NM, ("-C", "-n")),
    (BinwalkTool, ExternalToolType.BINWALK, ("--signature",)),
)


class RecordingFakeRunner:
    def __init__(self, result=None):
        self.result = result or _process_result()
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


class EmptyPlanner:
    def plan(self, **_values):
        return ()


class RecordingAIClient(BaseAIClient):
    def __init__(self):
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "analysis without a flag"


def _process_result(**changes):
    values = {
        "status": ExternalProcessStatus.COMPLETED,
        "started": True,
        "executable": "registered",
        "arguments": (),
        "stdout": "0 0x0 PNG image\nFLAG{tool_candidate}",
        "stderr": "warning",
        "exit_code": 0,
        "duration_seconds": 0.01,
        "timed_out": False,
        "stdout_truncated": False,
        "stderr_truncated": False,
        "error_type": None,
        "error_message": None,
    }
    values.update(changes)
    return ExternalProcessResult(**values)


def _allowed(tmp_path, tool_type, fixed):
    executable = (tmp_path / f"{tool_type.value}.exe").resolve()
    executable.write_bytes(b"placeholder; never executed")
    return AllowedTool(
        tool_type,
        executable,
        (),
        fixed,
        len(fixed) + 1,
        2.0,
        65_536,
        65_536,
        (ToolArgumentRule(ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, None),),
    )


def _adapter_environment(tmp_path, adapter_type, tool_type, fixed, result=None):
    registry = ExternalToolRegistry(
        (_allowed(tmp_path, tool_type, fixed),), tmp_path.resolve()
    )
    runner = RecordingFakeRunner(result)
    adapter = adapter_type(
        request_builder=ExternalToolRequestBuilder(registry),
        process_runner=runner,
    )
    return adapter, runner


def _action(target, tool_type, identifier="tool"):
    return IterationAction(
        identifier,
        IterationActionType.RUN_EXTERNAL_TOOL,
        IterationActionStatus.APPROVED,
        "Run tool",
        "Read-only analysis",
        50,
        "Collect evidence",
        None,
        True,
        {"tool_type": tool_type, "target_path": target},
    )


def _session(manager, *actions):
    session = manager.create_session("phase6", NOW)
    proposed = tuple(replace(item, status=IterationActionStatus.PROPOSED) for item in actions)
    session = manager.add_pending_actions(session, proposed, NOW)
    for action in actions:
        session = manager.decide_action(session, action.action_id, True, NOW)
    return session


def _orchestrator(manager, coordinator):
    return IterationOrchestrator(
        state_manager=manager,
        action_planner=EmptyPlanner(),
        stop_evaluator=IterationStopEvaluator(),
        budget_manager=IterationBudgetManager(),
        local_coordinator=None,
        agent_coordinator=None,
        feedback_coordinator=None,
        external_tool_coordinator=coordinator,
    )


def _context(session, tmp_path, *, budget=None):
    return IterationRunContext(
        session,
        IterationUsage(),
        budget or IterationBudget(),
        None,
        None,
        None,
        None,
        None,
        LATER,
        1.0,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
    )


@pytest.mark.parametrize(("adapter_type", "tool_type", "fixed"), TOOL_CASES)
def test_all_seven_tools_follow_complete_approved_iteration_path(
    tmp_path, adapter_type, tool_type, fixed
):
    target = (tmp_path / "target.bin").resolve()
    target.write_bytes(b"fixture")
    adapter, runner = _adapter_environment(
        tmp_path, adapter_type, tool_type, fixed
    )
    manager = IterationStateManager()
    action = _action(target, tool_type)
    session = _session(manager, action)
    coordinator = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    )

    result = _orchestrator(manager, coordinator).run_once(_context(session, tmp_path))

    assert len(runner.requests) == 1
    assert runner.requests[0].arguments == (*fixed, str(target))
    assert result.external_tool_execution is not None
    assert result.external_tool_execution.step.external_tool_result is not None
    assert result.external_tool_execution.step.external_tool_result.tool_type is tool_type
    assert result.usage.external_tool_runs_used == 1
    assert result.usage.tool_counts == {tool_type: 1}
    assert result.session.pending_actions == ()
    assert result.session.flag_candidates == ()
    assert result.session.primary_flag is None


def test_orchestrator_executes_only_one_of_multiple_approved_actions(tmp_path):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    adapter, runner = _adapter_environment(
        tmp_path, StringsTool, ExternalToolType.STRINGS, ()
    )
    manager = IterationStateManager()
    first = _action(target, ExternalToolType.STRINGS, "first")
    second = replace(_action(target, ExternalToolType.STRINGS, "second"), priority=10)
    session = _session(manager, first, second)
    coordinator = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    )

    result = _orchestrator(manager, coordinator).run_once(_context(session, tmp_path))

    assert len(runner.requests) == 1
    assert result.selected_action.action_id == "first"
    assert tuple(item.action_id for item in result.session.pending_actions) == ("second",)


def test_budget_denial_and_policy_skip_have_distinct_usage_rules(tmp_path):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    adapter, runner = _adapter_environment(
        tmp_path, FileTool, ExternalToolType.FILE, ()
    )
    manager = IterationStateManager()
    action = _action(target, ExternalToolType.FILE)
    session = _session(manager, action)
    coordinator = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    )
    denied = _orchestrator(manager, coordinator).run_once(
        _context(session, tmp_path, budget=IterationBudget(max_external_tool_runs=0))
    )
    assert runner.requests == []
    assert denied.usage.external_tool_runs_used == 0

    working = tmp_path / "working"
    working.mkdir()
    manager = IterationStateManager()
    session = _session(manager, action)
    skipped = _orchestrator(manager, coordinator).run_once(
        replace(_context(session, tmp_path), working_directory=working.resolve())
    )
    assert runner.requests == []
    assert skipped.external_tool_execution.tool_iteration_result.status is (
        ExternalToolIterationStatus.SKIPPED
    )
    assert skipped.usage.external_tool_runs_used == 1


def test_policy_and_coordinator_reject_unsafe_targets_types_and_arguments(tmp_path):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    allowed = _allowed(tmp_path, ExternalToolType.FILE, ())
    registry = ExternalToolRegistry((allowed,), tmp_path.resolve())
    builder = ExternalToolRequestBuilder(registry)
    runner = RecordingFakeRunner()
    adapter = FileTool(request_builder=builder, process_runner=runner)

    denied_argument = builder.build(
        ExternalToolInvocation(
            ExternalToolType.FILE,
            ("--unsafe-option", str(target)),
            tmp_path.resolve(),
        )
    )
    assert denied_argument.decision is ToolPolicyDecision.DENY

    with patch.object(Path, "is_symlink", lambda self: self == target):
        symlink_result = adapter.execute(
            ToolRequest(
                ChallengeInput("question"),
                tmp_path.resolve(),
                {TARGET_PATH_METADATA_KEY: target},
            )
        )
    assert symlink_result.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []

    manager = IterationStateManager()
    custom = _action(target, ExternalToolType.CUSTOM)
    session = _session(manager, custom)
    coordinator = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    )
    with pytest.raises(ValueError, match="CUSTOM"):
        coordinator.execute_action(
            session=session,
            action_id=custom.action_id,
            challenge=ChallengeInput("question"),
            working_directory=tmp_path.resolve(),
            updated_at=LATER,
        )
    assert runner.requests == []


@pytest.mark.parametrize(
    ("process_status", "exit_code", "expected"),
    [
        (ExternalProcessStatus.COMPLETED, 3, ExternalToolStatus.COMPLETED),
        (ExternalProcessStatus.TIMED_OUT, None, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.FAILED, None, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.REJECTED, None, ExternalToolStatus.SKIPPED),
    ],
)
def test_process_states_are_preserved_without_retry(
    tmp_path, process_status, exit_code, expected
):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    process = _process_result(status=process_status, exit_code=exit_code)
    adapter, runner = _adapter_environment(
        tmp_path, ObjdumpTool, ExternalToolType.OBJDUMP, ("-d", "-f", "-h"), process
    )
    request = ToolRequest(
        ChallengeInput("question"),
        tmp_path.resolve(),
        {TARGET_PATH_METADATA_KEY: target},
    )
    result = adapter.execute(request)
    assert result.status is expected
    assert result.exit_code == exit_code
    assert len(runner.requests) == 1
    if exit_code:
        assert "成功" not in result.summary


def test_output_limits_binwalk_warning_and_formatter_do_not_copy_streams(tmp_path):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    stdout = "0 0x0 PNG image\n" + "S" * 65_000
    stderr = "E" * 65_536
    process = _process_result(
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=True,
        stderr_truncated=True,
    )
    adapter, _runner = _adapter_environment(
        tmp_path,
        BinwalkTool,
        ExternalToolType.BINWALK,
        ("--signature",),
        process,
    )
    manager = IterationStateManager()
    action = _action(target, ExternalToolType.BINWALK)
    session = _session(manager, action)
    execution = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    ).execute_action(
        session=session,
        action_id=action.action_id,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    tool_result = execution.tool_iteration_result.tool_result
    assert len(tool_result.stdout) <= 65_536
    assert len(tool_result.stderr) <= 65_536
    assert any(item.source == "binwalk.warning" for item in tool_result.evidence)
    formatted = ExternalToolEvidenceFormatter().format(
        (execution.tool_iteration_result,) * 25
    )
    assert len(formatted) <= 20
    assert all(len(item) <= 1_000 for item in formatted)
    assert sum(map(len, formatted)) <= 10_000
    combined = "".join(formatted)
    assert stdout not in combined and stderr not in combined


def test_repeat_and_difference_fingerprints_do_not_stop_session(tmp_path):
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    adapter, runner = _adapter_environment(
        tmp_path, StringsTool, ExternalToolType.STRINGS, ()
    )
    manager = IterationStateManager()
    coordinator = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,), max_runs_per_tool=3
    )
    first = _action(target, ExternalToolType.STRINGS, "first")
    session = _session(manager, first)
    first_result = coordinator.execute_action(
        session=session,
        action_id="first",
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    second = _action(target, ExternalToolType.STRINGS, "second")
    session = manager.add_pending_actions(
        first_result.session,
        (replace(second, status=IterationActionStatus.PROPOSED),),
        LATER,
    )
    session = manager.decide_action(session, "second", True, LATER)
    repeated = coordinator.execute_action(
        session=session,
        action_id="second",
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER + timedelta(seconds=1),
    )
    assert repeated.tool_iteration_result.status is ExternalToolIterationStatus.REPEATED
    assert repeated.session.status.value == "active"

    runner.result = _process_result(stdout="different")
    third = _action(target, ExternalToolType.STRINGS, "third")
    session = manager.add_pending_actions(
        repeated.session,
        (replace(third, status=IterationActionStatus.PROPOSED),),
        repeated.session.updated_at,
    )
    session = manager.decide_action(session, "third", True, session.updated_at)
    distinct = coordinator.execute_action(
        session=session,
        action_id="third",
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=session.updated_at,
    )
    assert distinct.tool_iteration_result.status is ExternalToolIterationStatus.COMPLETED


def test_formatter_is_passed_only_as_agent_local_knowledge_without_tool_rerun(
    tmp_path, monkeypatch
):
    for name in ("OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, f"secret-{name}")
    target = (tmp_path / "target").resolve()
    target.write_bytes(b"fixture")
    adapter, runner = _adapter_environment(
        tmp_path, StringsTool, ExternalToolType.STRINGS, ()
    )
    manager = IterationStateManager()
    action = _action(target, ExternalToolType.STRINGS)
    execution = ExternalToolIterationCoordinator(
        state_manager=manager, tools=(adapter,)
    ).execute_action(
        session=_session(manager, action),
        action_id=action.action_id,
        challenge=ChallengeInput("question"),
        working_directory=tmp_path.resolve(),
        updated_at=LATER,
    )
    knowledge = ExternalToolEvidenceFormatter().format(
        (execution.tool_iteration_result,)
    )
    original = AgentInput(ChallengeInput("question"), "Unknown", "context", (), {})
    rev_input = replace(original, category="Rev", local_knowledge=knowledge)
    forensic_input = replace(original, category="Misc", local_knowledge=knowledge)
    rev_client = RecordingAIClient()
    forensic_client = RecordingAIClient()
    before = len(runner.requests)
    RevAgent(rev_client).analyze(rev_input)
    ForensicsAgent(forensic_client).analyze(forensic_input)
    assert len(runner.requests) == before
    assert original.local_knowledge == () and dict(original.metadata) == {}
    assert dict(rev_input.metadata) == dict(forensic_input.metadata) == {}
    prompts = "".join(rev_client.prompts + forensic_client.prompts)
    assert "tool=strings" in prompts
    assert all(f"secret-{name}" not in prompts for name in (
        "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN"
    ))


def test_phase6_sources_have_no_direct_execution_or_unsafe_binwalk_options():
    adapter_source = "\n".join(
        inspect.getsource(item) for item, _tool_type, _fixed in TOOL_CASES
    )
    binwalk_source = inspect.getsource(BinwalkTool)
    assert "subprocess" not in adapter_source
    assert "shell=" not in adapter_source
    assert "which(" not in adapter_source
    for option in (
        '"-e"',
        '"--extract"',
        '"-M"',
        '"--matryoshka"',
        '"--run-as"',
        '"--directory"',
        '"--dd"',
    ):
        assert option not in binwalk_source
