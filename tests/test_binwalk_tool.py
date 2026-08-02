import inspect
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.external_tools import (
    TARGET_PATH_METADATA_KEY,
    AllowedTool,
    BaseExternalTool,
    BinwalkAnalysis,
    BinwalkEntry,
    BinwalkParser,
    BinwalkTool,
    ExternalProcessResult,
    ExternalProcessStatus,
    ExternalToolRegistry,
    ExternalToolRequestBuilder,
    ExternalToolStatus,
    ExternalToolType,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolRequest,
)


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
        "executable": "binwalk",
        "arguments": (),
        "stdout": "0 0x0 PNG image\n1024 0x400 Zip archive data",
        "stderr": "",
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


def _environment(tmp_path, result=None, *, registered=True):
    tools = ()
    if registered:
        executable = (tmp_path / "binwalk.exe").resolve()
        executable.write_bytes(b"test executable placeholder")
        tools = (
            AllowedTool(
                tool_type=ExternalToolType.BINWALK,
                executable=executable,
                allowed_argument_prefixes=(),
                allowed_exact_arguments=("--signature",),
                max_arguments=2,
                timeout_seconds=2.0,
                max_stdout_bytes=65_536,
                max_stderr_bytes=65_536,
                argument_rules=(
                    ToolArgumentRule(
                        ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, None
                    ),
                ),
            ),
        )
    registry = ExternalToolRegistry(tools, tmp_path.resolve())
    return (
        ExternalToolRequestBuilder(registry),
        RecordingFakeProcessRunner(result or _process_result()),
        registry,
    )


def _request(tmp_path, *, target=None, metadata=None, working_directory=None):
    target = target or (tmp_path / "sample.bin").resolve()
    target.write_bytes(b"fixture")
    if metadata is None:
        metadata = {TARGET_PATH_METADATA_KEY: target}
    return ToolRequest(
        ChallengeInput("question"),
        working_directory or tmp_path.resolve(),
        metadata,
    )


def test_binwalk_dtos_are_frozen_and_slotted():
    entry = BinwalkEntry(0, "0x0", "PNG image")
    analysis = BinwalkAnalysis((entry,), True, False)
    for value in (entry, analysis):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)


def test_binwalk_dtos_validate_offset_description_and_entry_limit():
    with pytest.raises(ValueError, match="decimal_offset"):
        BinwalkEntry(-1, "0x0", "bad")
    with pytest.raises(ValueError, match="hexadecimal_offset"):
        BinwalkEntry(0, "", "bad")
    with pytest.raises(ValueError, match="500"):
        BinwalkEntry(0, "0x0", "x" * 501)
    entry = BinwalkEntry(0, "0x0", "entry")
    with pytest.raises(ValueError, match="100"):
        BinwalkAnalysis((entry,) * 101, True, True)


def test_parser_reads_standard_output_in_input_order():
    output = """DECIMAL       HEXADECIMAL     DESCRIPTION
--------------------------------------------------------------------------------
0             0x0             PNG image, 800 x 600
1024          0x400           Zip archive data
2048          0x800           gzip compressed data
"""
    analysis = BinwalkParser().parse(output)
    assert analysis.entries == (
        BinwalkEntry(0, "0x0", "PNG image, 800 x 600"),
        BinwalkEntry(1024, "0x400", "Zip archive data"),
        BinwalkEntry(2048, "0x800", "gzip compressed data"),
    )
    assert analysis.parsed
    assert not analysis.truncated


def test_parser_ignores_empty_header_separator_invalid_and_negative_lines():
    output = """
DECIMAL HEXADECIMAL DESCRIPTION
------------------------------
invalid
-1 0x0 negative
12 not-hex invalid
20 0x14 valid description
"""
    assert BinwalkParser().parse(output).entries == (
        BinwalkEntry(20, "0x14", "valid description"),
    )


def test_parser_deduplicates_exact_offset_description_and_is_deterministic():
    output = "1 0x1 same\n1 0x01 same\n1 0x1 different"
    parser = BinwalkParser()
    first = parser.parse(output)
    second = parser.parse(output)
    assert first == second
    assert first.entries == (
        BinwalkEntry(1, "0x1", "same"),
        BinwalkEntry(1, "0x1", "different"),
    )


def test_parser_truncates_description_and_entries_safely():
    output = "\n".join(
        f"{index} 0x{index:X} {'x' * 600}" for index in range(101)
    )
    analysis = BinwalkParser().parse(output)
    assert len(analysis.entries) == 100
    assert all(len(entry.description) == 500 for entry in analysis.entries)
    assert analysis.truncated


def test_invalid_output_returns_unparsed_empty_analysis():
    assert BinwalkParser().parse("not binwalk output") == BinwalkAnalysis(
        (), False, False
    )


def test_adapter_contract_type_fixed_arguments_and_policy_request(tmp_path):
    builder, runner, registry = _environment(tmp_path)
    request = _request(tmp_path)
    adapter = BinwalkTool(request_builder=builder, process_runner=runner)

    result = adapter.execute(request)

    assert isinstance(adapter, BaseExternalTool)
    assert adapter.tool_type is ExternalToolType.BINWALK
    assert result.status is ExternalToolStatus.COMPLETED
    assert len(runner.requests) == 1
    process_request = runner.requests[0]
    assert process_request.executable == registry.get(ExternalToolType.BINWALK).executable
    assert process_request.arguments == (
        "--signature",
        str(request.metadata[TARGET_PATH_METADATA_KEY]),
    )
    assert not set(process_request.arguments) & {
        "-e",
        "--extract",
        "-M",
        "--matryoshka",
        "--run-as",
        "--directory",
        "--dd",
    }


@pytest.mark.parametrize(
    "invalid_target", [None, "", "relative.bin", Path("relative.bin")]
)
def test_invalid_target_never_reaches_policy_runner(tmp_path, invalid_target):
    builder, runner, _ = _environment(tmp_path)
    metadata = (
        {} if invalid_target is None else {TARGET_PATH_METADATA_KEY: invalid_target}
    )
    result = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path, metadata=metadata)
    )
    assert result.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []


def test_unregistered_or_outside_target_is_skipped_without_runner(tmp_path):
    builder, runner, _ = _environment(tmp_path, registered=False)
    unregistered = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert unregistered.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []

    working = tmp_path / "working"
    working.mkdir()
    outside = (tmp_path / "outside.bin").resolve()
    outside.write_bytes(b"outside")
    builder, runner, _ = _environment(tmp_path)
    denied = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path, target=outside, working_directory=working.resolve())
    )
    assert denied.status is ExternalToolStatus.SKIPPED
    assert runner.requests == []


@pytest.mark.parametrize(
    ("process_status", "expected_status"),
    [
        (ExternalProcessStatus.TIMED_OUT, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.FAILED, ExternalToolStatus.FAILED),
        (ExternalProcessStatus.REJECTED, ExternalToolStatus.SKIPPED),
    ],
)
def test_abnormal_status_is_mapped_and_runner_is_not_retried(
    tmp_path, process_status, expected_status
):
    process = _process_result(
        status=process_status,
        exit_code=None,
        error_message="process detail",
    )
    builder, runner, _ = _environment(tmp_path, process)
    result = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert result.status is expected_status
    assert result.stdout is process.stdout
    assert result.stderr is process.stderr
    assert result.exit_code is None
    assert len(runner.requests) == 1


def test_nonzero_exit_is_retained_without_claiming_normal_completion(tmp_path):
    builder, runner, _ = _environment(tmp_path, _process_result(exit_code=2))
    result = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert result.status is ExternalToolStatus.COMPLETED
    assert result.exit_code == 2
    assert result.summary == "binwalkは実行されましたが、正常終了しませんでした。"


def test_entries_and_stderr_are_structured_without_confirming_flag(tmp_path):
    process = _process_result(
        stdout="1024 0x400 Zip FLAG{candidate}",
        stderr="warning line",
    )
    builder, runner, _ = _environment(tmp_path, process)
    result = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert result.stdout is process.stdout
    assert result.stderr is process.stderr
    assert [(item.source, item.detail, item.confidence) for item in result.evidence] == [
        ("binwalk.signature", "offset=1024 (0x400): Zip FLAG{candidate}", 70),
        ("binwalk.stderr", "warning line", 70),
    ]
    assert result.status is ExternalToolStatus.COMPLETED


def test_evidence_is_limited_and_truncation_warning_is_always_retained(tmp_path):
    output = "\n".join(f"{index} 0x{index:X} {'x' * 600}" for index in range(60))
    builder, runner, _ = _environment(
        tmp_path,
        _process_result(stdout=output, stderr="warning", stdout_truncated=True),
    )
    result = BinwalkTool(request_builder=builder, process_runner=runner).execute(
        _request(tmp_path)
    )
    assert len(result.evidence) == 50
    assert all(len(item.detail) <= 500 for item in result.evidence)
    assert result.evidence[-1].source == "binwalk.warning"
    assert result.evidence[-1].detail == (
        "binwalkの標準出力は上限により省略されています。"
    )


def test_adapter_and_parser_contain_no_forbidden_execution_features():
    source = "\n".join(
        inspect.getsource(item) for item in (BinwalkTool, BinwalkParser)
    )
    for forbidden in (
        "subprocess",
        "shell=",
        "os.system",
        "which(",
        "importlib",
        "FlagExtractor",
        "OpenAI",
        "socket",
        "mkdir",
        "write_",
        "--extract",
        "--matryoshka",
    ):
        assert forbidden not in source
