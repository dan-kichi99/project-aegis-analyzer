import inspect
from pathlib import Path

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.external_tools import (
    TARGET_PATH_METADATA_KEY,
    AllowedTool,
    BaseExternalTool,
    ExternalProcessResult,
    ExternalProcessStatus,
    ExternalToolRegistry,
    ExternalToolRequestBuilder,
    ExternalToolStatus,
    ExternalToolType,
    NmTool,
    ObjdumpTool,
    ReadelfTool,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolRequest,
)
from app.external_tools.tool_adapter import BaseBinaryInspectionTool


class RecordingFakeProcessRunner:
    def __init__(self, result: ExternalProcessResult) -> None:
        self.result = result
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return self.result


FIXED_ARGUMENTS = {
    ExternalToolType.READELF: ("-W", "-h", "-l", "-S", "-s"),
    ExternalToolType.OBJDUMP: ("-d", "-f", "-h"),
    ExternalToolType.NM: ("-C", "-n"),
}


def _process_result(**changes):
    values = {
        "status": ExternalProcessStatus.COMPLETED,
        "started": True,
        "executable": "registered-tool",
        "arguments": (),
        "stdout": "header\nsymbol",
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
    arguments = FIXED_ARGUMENTS[tool_type]
    return AllowedTool(
        tool_type=tool_type,
        executable=executable,
        allowed_argument_prefixes=(),
        allowed_exact_arguments=arguments,
        max_arguments=len(arguments) + 1,
        timeout_seconds=2.0,
        max_stdout_bytes=65_536,
        max_stderr_bytes=65_536,
        argument_rules=(
            ToolArgumentRule(ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, None),
        ),
    )


def _environment(tmp_path, result=None, registered_types=None):
    if registered_types is None:
        registered_types = tuple(FIXED_ARGUMENTS)
    tools = []
    for tool_type in registered_types:
        executable = (tmp_path / f"{tool_type.value}.exe").resolve()
        executable.write_bytes(b"test executable placeholder")
        tools.append(_allowed(tool_type, executable))
    registry = ExternalToolRegistry(tuple(tools), tmp_path.resolve())
    return (
        ExternalToolRequestBuilder(registry),
        RecordingFakeProcessRunner(result or _process_result()),
        registry,
    )


def _request(tmp_path, *, metadata=None, target=None, working_directory=None):
    target = target or (tmp_path / "sample.bin").resolve()
    target.write_bytes(b"binary fixture")
    if metadata is None:
        metadata = {TARGET_PATH_METADATA_KEY: target}
    return ToolRequest(
        ChallengeInput("question"),
        working_directory or tmp_path.resolve(),
        metadata,
    )


@pytest.mark.parametrize(
    ("adapter_type", "tool_type"),
    [
        (ReadelfTool, ExternalToolType.READELF),
        (ObjdumpTool, ExternalToolType.OBJDUMP),
        (NmTool, ExternalToolType.NM),
    ],
)
def test_binary_adapters_satisfy_contract_and_have_correct_type(
    tmp_path, adapter_type, tool_type
):
    builder, runner, _ = _environment(tmp_path)
    adapter = adapter_type(request_builder=builder, process_runner=runner)
    assert isinstance(adapter, BaseExternalTool)
    assert adapter.tool_type is tool_type


@pytest.mark.parametrize(
    ("adapter_type", "tool_type"),
    [
        (ReadelfTool, ExternalToolType.READELF),
        (ObjdumpTool, ExternalToolType.OBJDUMP),
        (NmTool, ExternalToolType.NM),
    ],
)
def test_fixed_arguments_pass_policy_and_runner_is_called_once(
    tmp_path, adapter_type, tool_type
):
    builder, runner, registry = _environment(tmp_path)
    request = _request(tmp_path)

    result = adapter_type(request_builder=builder, process_runner=runner).execute(request)

    assert result.status is ExternalToolStatus.COMPLETED
    assert len(runner.requests) == 1
    process_request = runner.requests[0]
    assert process_request.executable == registry.get(tool_type).executable
    assert process_request.arguments == (
        *FIXED_ARGUMENTS[tool_type],
        str(request.metadata[TARGET_PATH_METADATA_KEY]),
    )


@pytest.mark.parametrize(
    "invalid_target", [None, "", "relative.bin", Path("relative.bin")]
)
def test_missing_empty_or_relative_target_never_calls_runner(tmp_path, invalid_target):
    builder, runner, _ = _environment(tmp_path)
    metadata = (
        {} if invalid_target is None else {TARGET_PATH_METADATA_KEY: invalid_target}
    )

    result = ReadelfTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path, metadata=metadata)
    )

    assert result.status in (ExternalToolStatus.NOT_RUN, ExternalToolStatus.SKIPPED)
    assert runner.requests == []


def test_unregistered_tool_is_policy_denied_without_runner(tmp_path):
    builder, runner, _ = _environment(
        tmp_path, registered_types=(ExternalToolType.NM,)
    )

    result = ReadelfTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.status is ExternalToolStatus.SKIPPED
    assert result.error_message
    assert runner.requests == []


def test_target_outside_working_directory_is_denied_without_runner(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    outside = (tmp_path / "outside.bin").resolve()
    outside.write_bytes(b"outside")
    builder, runner, _ = _environment(tmp_path)

    result = ObjdumpTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path, target=outside, working_directory=working.resolve())
    )

    assert result.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []


@pytest.mark.parametrize(
    ("process_status", "expected_status"),
    [
        (ExternalProcessStatus.TIMED_OUT, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.FAILED, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.REJECTED, ExternalToolStatus.SKIPPED),
    ],
)
def test_abnormal_process_status_mapping_and_output_preservation(
    tmp_path, process_status, expected_status
):
    process = _process_result(
        status=process_status,
        exit_code=None,
        error_message="process detail",
    )
    builder, runner, _ = _environment(tmp_path, process)

    result = NmTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.status is expected_status
    assert result.stdout is process.stdout
    assert result.stderr is process.stderr
    assert result.exit_code is process.exit_code
    assert len(runner.requests) == 1


def test_nonzero_completed_result_is_retained_without_claiming_success(tmp_path):
    builder, runner, _ = _environment(tmp_path, _process_result(exit_code=2))

    result = ReadelfTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert result.status is ExternalToolStatus.COMPLETED
    assert result.exit_code == 2
    assert result.summary == "readelfによる静的構造解析を実行しました。"
    assert "成功" not in result.summary


@pytest.mark.parametrize(
    ("adapter_type", "summary"),
    [
        (ReadelfTool, "readelfによる静的構造解析を実行しました。"),
        (ObjdumpTool, "objdumpによるヘッダー・逆アセンブル解析を実行しました。"),
        (NmTool, "nmによるシンボル解析を実行しました。"),
    ],
)
def test_completed_summary_is_fixed_and_bounded(tmp_path, adapter_type, summary):
    builder, runner, _ = _environment(tmp_path)
    result = adapter_type(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert result.summary == summary
    assert len(result.summary) <= 500


def test_stdout_stderr_become_bounded_evidence_without_flag_confirmation(tmp_path):
    output = "\n".join(["FLAG{candidate}", *("x" * 600 for _ in range(55))])
    builder, runner, _ = _environment(
        tmp_path, _process_result(stdout=output, stderr="warning")
    )

    result = ObjdumpTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )

    assert len(result.evidence) == 50
    assert all(len(item.detail) <= 500 for item in result.evidence)
    assert result.evidence[0].source == "objdump.stdout"
    assert result.evidence[0].detail == "FLAG{candidate}"
    assert result.evidence[0].confidence == 70
    assert result.status is ExternalToolStatus.COMPLETED


def test_binary_adapters_contain_no_execution_search_or_communication_code():
    source = "\n".join(
        inspect.getsource(item)
        for item in (BaseBinaryInspectionTool, ReadelfTool, ObjdumpTool, NmTool)
    )
    for forbidden in (
        "subprocess",
        "shell=",
        "os.system",
        "which(",
        "FlagExtractor",
        "OpenAI",
        "socket",
    ):
        assert forbidden not in source
