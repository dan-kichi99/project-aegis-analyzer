import inspect

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.external_tools import (
    TARGET_PATH_METADATA_KEY,
    AllowedTool,
    BaseExternalTool,
    ExifTool,
    ExternalProcessResult,
    ExternalProcessStatus,
    ExternalToolRegistry,
    ExternalToolRequestBuilder,
    ExternalToolStatus,
    ExternalToolType,
    FileTool,
    StringsTool,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolRequest,
)
from app.external_tools.tool_adapter import BaseFileExternalTool


class RecordingFakeProcessRunner:
    def __init__(self, result: ExternalProcessResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


def _process_result(**changes):
    values = {
        "status": ExternalProcessStatus.COMPLETED,
        "started": True,
        "executable": "registered-tool",
        "arguments": (),
        "stdout": "first evidence\nsecond evidence",
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


def _allowed(tool_type, executable):
    exact = ("-j",) if tool_type is ExternalToolType.EXIFTOOL else ()
    return AllowedTool(
        tool_type=tool_type,
        executable=executable,
        allowed_argument_prefixes=(),
        allowed_exact_arguments=exact,
        max_arguments=2,
        timeout_seconds=2.0,
        max_stdout_bytes=65_536,
        max_stderr_bytes=65_536,
        argument_rules=(
            ToolArgumentRule(ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, None),
        ),
    )


def _environment(tmp_path, result=None, registered_types=None):
    registered_types = registered_types or (
        ExternalToolType.STRINGS,
        ExternalToolType.FILE,
        ExternalToolType.EXIFTOOL,
    )
    tools = []
    for tool_type in registered_types:
        executable = (tmp_path / f"{tool_type.value}.exe").resolve()
        executable.write_bytes(b"test executable placeholder")
        tools.append(_allowed(tool_type, executable))
    registry = ExternalToolRegistry(tuple(tools), tmp_path.resolve())
    runner = RecordingFakeProcessRunner(result or _process_result())
    builder = ExternalToolRequestBuilder(registry)
    return builder, runner, registry


def _request(tmp_path, target=None, working_directory=None):
    target = target or (tmp_path / "sample.bin").resolve()
    target.write_bytes(b"sample")
    return ToolRequest(
        challenge=ChallengeInput("question"),
        working_directory=working_directory or tmp_path.resolve(),
        metadata={TARGET_PATH_METADATA_KEY: target},
    )


@pytest.mark.parametrize(
    ("adapter_type", "tool_type", "prefix"),
    [
        (StringsTool, ExternalToolType.STRINGS, ()),
        (FileTool, ExternalToolType.FILE, ()),
        (ExifTool, ExternalToolType.EXIFTOOL, ("-j",)),
    ],
)
def test_adapters_use_registry_policy_and_call_runner_once(
    tmp_path, adapter_type, tool_type, prefix
):
    builder, runner, registry = _environment(tmp_path)
    request = _request(tmp_path)
    adapter = adapter_type(request_builder=builder, process_runner=runner)

    result = adapter.execute(request)

    assert isinstance(adapter, BaseExternalTool)
    assert adapter.tool_type is tool_type
    assert result.status is ExternalToolStatus.COMPLETED
    assert len(runner.requests) == 1
    process_request = runner.requests[0]
    assert process_request.executable == registry.get(tool_type).executable
    assert process_request.arguments == (*prefix, str(request.metadata["target_path"]))
    assert process_request.working_directory == tmp_path.resolve()


def test_process_output_is_preserved_and_converted_to_structured_evidence(tmp_path):
    process_result = _process_result(stdout="alpha\nbeta", stderr="warning")
    builder, runner, _ = _environment(tmp_path, process_result)

    result = StringsTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.stdout is process_result.stdout
    assert result.stderr is process_result.stderr
    assert [(item.source, item.detail, item.confidence) for item in result.evidence] == [
        ("strings:stdout", "alpha", None),
        ("strings:stdout", "beta", None),
        ("strings:stderr", "warning", None),
    ]
    assert len(result.summary) <= 500


def test_evidence_count_and_detail_length_are_bounded(tmp_path):
    output = "\n".join("x" * 600 for _ in range(60))
    builder, runner, _ = _environment(tmp_path, _process_result(stdout=output))

    result = FileTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert len(result.evidence) == 50
    assert all(len(item.detail) <= 500 for item in result.evidence)


def test_unregistered_tool_is_skipped_without_calling_runner(tmp_path):
    builder, runner, _ = _environment(
        tmp_path, registered_types=(ExternalToolType.FILE,)
    )

    result = StringsTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []


def test_path_outside_working_directory_is_denied_without_runner(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    target = (tmp_path / "outside.bin").resolve()
    target.write_bytes(b"outside")
    builder, runner, _ = _environment(tmp_path)

    result = FileTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path, target=target, working_directory=working.resolve())
    )

    assert result.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []


@pytest.mark.parametrize(
    ("process_status", "exit_code", "tool_status"),
    [
        (ExternalProcessStatus.COMPLETED, 1, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.FAILED, None, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.TIMED_OUT, None, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.REJECTED, None, ExternalToolStatus.SKIPPED),
    ],
)
def test_process_status_is_mapped_without_a_second_run(
    tmp_path, process_status, exit_code, tool_status
):
    process_result = _process_result(
        status=process_status,
        exit_code=exit_code,
        error_message="detail",
    )
    builder, runner, _ = _environment(tmp_path, process_result)

    result = ExifTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.status is tool_status
    assert result.error_message == "detail"
    assert len(runner.requests) == 1


def test_missing_adapter_input_does_not_run_process(tmp_path):
    builder, runner, _ = _environment(tmp_path)
    request = ToolRequest(ChallengeInput("question"), None, {})

    result = StringsTool(request_builder=builder, process_runner=runner).execute(request)

    assert result.status is ExternalToolStatus.NOT_RUN
    assert runner.requests == []


def test_adapters_do_not_call_subprocess_or_network_directly():
    source = inspect.getsource(BaseFileExternalTool)
    assert "subprocess" not in source
    assert "shell=" not in source
    assert "socket" not in source
    assert "OpenAI" not in source
