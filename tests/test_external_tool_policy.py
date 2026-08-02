import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from app.external_tools import (
    AllowedTool,
    ExternalToolInvocation,
    ExternalToolRegistry,
    ExternalToolRequestBuilder,
    ExternalToolType,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolPolicyDecision,
    ToolPolicyDenialReason,
)


def _tool(tool_type=ExternalToolType.FILE, executable=None, **changes):
    values = {
        "tool_type": tool_type,
        "executable": executable or Path(sys.executable).resolve(),
        "allowed_argument_prefixes": ("--output=",),
        "allowed_exact_arguments": ("--brief",),
        "max_arguments": 5,
        "timeout_seconds": 3.0,
        "max_stdout_bytes": 1024,
        "max_stderr_bytes": 2048,
        "argument_rules": (),
    }
    values.update(changes)
    return AllowedTool(**values)


def _registry(tmp_path, tools=None):
    return ExternalToolRegistry(
        tuple(tools or (_tool(),)),
        tmp_path.resolve(),
    )


def _invocation(tmp_path, *arguments, **changes):
    values = {
        "tool_type": ExternalToolType.FILE,
        "arguments": tuple(arguments),
        "working_directory": tmp_path.resolve(),
    }
    values.update(changes)
    return ExternalToolInvocation(**values)


def test_policy_dtos_are_frozen_and_slotted(tmp_path):
    tool = _tool()
    invocation = _invocation(tmp_path, "--brief")
    evaluation = ExternalToolRequestBuilder(_registry(tmp_path)).build(invocation)
    for value in (tool, invocation, evaluation):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)


def test_allowed_tool_validates_path_limits_rules_and_nul():
    with pytest.raises(ValueError, match="絶対"):
        _tool(executable=Path("relative.exe"))
    with pytest.raises(ValueError, match="max_arguments"):
        _tool(max_arguments=51)
    with pytest.raises(ValueError, match="timeout"):
        _tool(timeout_seconds=11)
    with pytest.raises(ValueError, match="max_stdout"):
        _tool(max_stdout_bytes=65_537)
    with pytest.raises(ValueError, match="空prefix"):
        _tool(allowed_argument_prefixes=("",))
    with pytest.raises(ValueError, match="NUL"):
        _tool(allowed_exact_arguments=("bad\0value",))
    with pytest.raises(ValueError, match="value"):
        ToolArgumentRule(ToolArgumentKind.PREFIX, "")
    with pytest.raises(ValueError, match="None"):
        ToolArgumentRule(ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, "value")


def test_invocation_validates_structure_limits_and_nul(tmp_path):
    with pytest.raises(ValueError, match="絶対"):
        _invocation(tmp_path, working_directory=Path("relative"))
    with pytest.raises(ValueError, match="50"):
        _invocation(tmp_path, *("x" for _ in range(51)))
    with pytest.raises(ValueError, match="4096"):
        _invocation(tmp_path, "x" * 4097)
    with pytest.raises(ValueError, match="NUL"):
        _invocation(tmp_path, "bad\0value")


def test_registry_validates_root(tmp_path):
    missing = (tmp_path / "missing").resolve()
    file_root = tmp_path / "root.txt"
    file_root.write_text("root", encoding="utf-8")
    with pytest.raises(ValueError, match="絶対"):
        ExternalToolRegistry((_tool(),), Path("relative"))
    for root in (missing, file_root.resolve()):
        with pytest.raises(ValueError, match="ディレクトリ"):
            ExternalToolRegistry((_tool(),), root)
    with (
        patch.object(Path, "is_symlink", return_value=True),
        pytest.raises(ValueError, match="symlink"),
    ):
        ExternalToolRegistry((_tool(),), tmp_path.resolve())


def test_registry_rejects_custom_duplicate_type_and_executable(tmp_path):
    with pytest.raises(ValueError, match="CUSTOM"):
        _registry(tmp_path, (_tool(ExternalToolType.CUSTOM),))
    with pytest.raises(ValueError, match="ToolType"):
        _registry(tmp_path, (_tool(), _tool()))
    with pytest.raises(ValueError, match="同じexecutable"):
        _registry(
            tmp_path,
            (_tool(), _tool(ExternalToolType.STRINGS)),
        )


def test_registry_rejects_invalid_executable(tmp_path):
    missing = (tmp_path / "missing.exe").resolve()
    with pytest.raises(ValueError, match="ファイル"):
        _registry(tmp_path, (_tool(executable=missing),))
    with pytest.raises(ValueError, match="ファイル"):
        _registry(tmp_path, (_tool(executable=tmp_path.resolve()),))
    checks = iter((False, True))
    with (
        patch.object(Path, "is_symlink", side_effect=lambda: next(checks)),
        pytest.raises(ValueError, match="symlink"),
    ):
        _registry(tmp_path)


def test_registry_preserves_order_get_and_missing(tmp_path):
    second_executable = tmp_path / "second.exe"
    second_executable.write_bytes(b"fixture")
    first = _tool()
    second = _tool(ExternalToolType.STRINGS, second_executable.resolve())
    registry = _registry(tmp_path, (first, second))
    assert registry.tools == (first, second)
    assert registry.get(ExternalToolType.FILE) is first
    assert registry.get(ExternalToolType.STRINGS) is second
    assert registry.get(ExternalToolType.NM) is None
    assert registry.is_registered(ExternalToolType.FILE)
    assert not registry.is_registered(ExternalToolType.NM)


def test_custom_and_unregistered_invocations_are_denied_in_priority_order(tmp_path):
    builder = ExternalToolRequestBuilder(_registry(tmp_path))
    custom = builder.build(
        _invocation(tmp_path, tool_type=ExternalToolType.CUSTOM)
    )
    missing = builder.build(_invocation(tmp_path, tool_type=ExternalToolType.NM))
    assert custom.matched_reasons[:2] == (
        ToolPolicyDenialReason.CUSTOM_TOOL_NOT_ALLOWED,
        ToolPolicyDenialReason.TOOL_NOT_REGISTERED,
    )
    assert custom.primary_reason is custom.matched_reasons[0]
    assert missing.primary_reason is ToolPolicyDenialReason.TOOL_NOT_REGISTERED
    assert custom.process_request is missing.process_request is None


def test_working_directory_root_and_child_are_allowed(tmp_path):
    child = tmp_path / "challenge"
    child.mkdir()
    builder = ExternalToolRequestBuilder(_registry(tmp_path))
    for directory in (tmp_path.resolve(), child.resolve()):
        result = builder.build(
            _invocation(tmp_path, "--brief", working_directory=directory)
        )
        assert result.allowed


def test_working_directory_invalid_symlink_and_outside_are_denied(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    builder = ExternalToolRequestBuilder(_registry(root))
    missing = (root / "missing").resolve()
    file_path = tmp_path / "file.txt"
    file_path.write_text("file", encoding="utf-8")
    outside = tmp_path / "root-evil"
    outside.mkdir()
    for directory in (missing, file_path.resolve()):
        result = builder.build(
            _invocation(root, "--brief", working_directory=directory)
        )
        assert ToolPolicyDenialReason.WORKING_DIRECTORY_INVALID in result.matched_reasons
    outside_result = builder.build(
        _invocation(root, "--brief", working_directory=outside.resolve())
    )
    assert outside_result.primary_reason is ToolPolicyDenialReason.WORKING_DIRECTORY_OUTSIDE_ROOT
    checks = iter((False, True))
    with patch.object(Path, "is_symlink", side_effect=lambda: next(checks)):
        symlink = builder.build(_invocation(root, "--brief"))
    assert symlink.primary_reason is ToolPolicyDenialReason.WORKING_DIRECTORY_INVALID


def test_exact_prefix_and_shell_characters_require_allowlist_match(tmp_path):
    builder = ExternalToolRequestBuilder(_registry(tmp_path))
    for argument in ("--brief", "--output=result.txt", "--output=;&&|>$`"):
        assert builder.build(_invocation(tmp_path, argument)).allowed
    for argument in ("--unknown", ";&&|>$`"):
        result = builder.build(_invocation(tmp_path, argument))
        assert result.primary_reason is ToolPolicyDenialReason.ARGUMENT_NOT_ALLOWED


def test_tool_specific_argument_count_is_denied(tmp_path):
    tool = _tool(max_arguments=1, allowed_exact_arguments=("a", "b"))
    result = ExternalToolRequestBuilder(_registry(tmp_path, (tool,))).build(
        _invocation(tmp_path, "a", "b")
    )
    assert result.primary_reason is ToolPolicyDenialReason.TOO_MANY_ARGUMENTS
    assert result.process_request is None


def test_path_rule_requires_absolute_existing_regular_file_within_both_roots(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    target = work / "target.bin"
    target.write_bytes(b"data")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    tool = _tool(
        allowed_argument_prefixes=(),
        allowed_exact_arguments=(),
        argument_rules=(
            ToolArgumentRule(ToolArgumentKind.PATH_WITHIN_WORKING_DIRECTORY, None),
        ),
    )
    builder = ExternalToolRequestBuilder(_registry(tmp_path, (tool,)))
    assert builder.build(
        _invocation(tmp_path, str(target.resolve()), working_directory=work.resolve())
    ).allowed
    for argument in (
        "relative.bin",
        str((work / "missing.bin").resolve()),
        str(work.resolve()),
        str(outside.resolve()),
    ):
        result = builder.build(
            _invocation(tmp_path, argument, working_directory=work.resolve())
        )
        assert result.primary_reason is ToolPolicyDenialReason.ARGUMENT_NOT_ALLOWED
    checks = iter((False, False, True))
    with patch.object(Path, "is_symlink", side_effect=lambda: next(checks)):
        symlink = builder.build(
            _invocation(tmp_path, str(target.resolve()), working_directory=work.resolve())
        )
    assert symlink.primary_reason is ToolPolicyDenialReason.ARGUMENT_NOT_ALLOWED


def test_multiple_rules_allow_any_match_but_require_every_argument_to_match(tmp_path):
    tool = _tool(
        allowed_argument_prefixes=(),
        allowed_exact_arguments=(),
        argument_rules=(
            ToolArgumentRule(ToolArgumentKind.EXACT, "--one"),
            ToolArgumentRule(ToolArgumentKind.PREFIX, "--format="),
        ),
    )
    builder = ExternalToolRequestBuilder(_registry(tmp_path, (tool,)))
    assert builder.build(_invocation(tmp_path, "--one", "--format=json")).allowed
    denied = builder.build(_invocation(tmp_path, "--one", "--unknown"))
    assert denied.primary_reason is ToolPolicyDenialReason.ARGUMENT_NOT_ALLOWED


def test_allow_builds_process_request_only_from_registered_limits(tmp_path):
    tool = _tool(
        timeout_seconds=4.5,
        max_stdout_bytes=123,
        max_stderr_bytes=456,
    )
    invocation = _invocation(tmp_path, "--brief")
    result = ExternalToolRequestBuilder(_registry(tmp_path, (tool,))).build(invocation)
    request = result.process_request
    assert result.decision is ToolPolicyDecision.ALLOW and result.allowed
    assert request is not None
    assert request.executable == tool.executable
    assert request.arguments == invocation.arguments
    assert request.working_directory == invocation.working_directory
    assert request.timeout_seconds == 4.5
    assert request.max_stdout_bytes == 123
    assert request.max_stderr_bytes == 456


def test_evaluation_enforces_consistency_and_primary_reason(tmp_path):
    allowed = ExternalToolRequestBuilder(_registry(tmp_path)).build(
        _invocation(tmp_path, "--brief")
    )
    with pytest.raises(ValueError, match="ALLOW"):
        replace(allowed, allowed=False)
    denied = ExternalToolRequestBuilder(_registry(tmp_path)).build(
        _invocation(tmp_path, "bad")
    )
    with pytest.raises(ValueError, match="先頭"):
        replace(denied, matched_reasons=(ToolPolicyDenialReason.INVALID_ARGUMENT,))
    with pytest.raises(ValueError, match="DENY"):
        replace(denied, process_request=allowed.process_request)
    with pytest.raises(ValueError, match="message"):
        replace(allowed, message="x" * 501)


def test_policy_layer_has_no_runner_subprocess_path_search_or_global_registry():
    modules = (
        "app.external_tools.tool_policy",
        "app.external_tools.tool_registry",
        "app.external_tools.tool_request_builder",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess",
        "externalprocessrunner",
        ".run(",
        "os.system",
        "which(",
        "getenv",
        "environ",
        "singleton",
    ):
        assert forbidden not in source
