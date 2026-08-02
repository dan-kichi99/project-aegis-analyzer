import inspect
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.challenge.challenge_input import ChallengeInput
from app.external_tools import (
    BaseExternalTool,
    ExternalToolStatus,
    ExternalToolType,
    ToolEvidence,
    ToolRequest,
    ToolResult,
)


class FakeExternalTool(BaseExternalTool):
    def __init__(self) -> None:
        self.requests = []

    @property
    def tool_type(self) -> ExternalToolType:
        return ExternalToolType.STRINGS

    def execute(self, request: ToolRequest) -> ToolResult:
        self.requests.append(request)
        return ToolResult(
            tool_type=self.tool_type,
            status=ExternalToolStatus.COMPLETED,
            summary="解析しました。",
            stdout="candidate string",
            stderr="",
            exit_code=0,
            evidence=(ToolEvidence("stdout", "候補を検出しました。", 80),),
            error_message=None,
        )


def _result() -> ToolResult:
    return ToolResult(
        ExternalToolType.FILE,
        ExternalToolStatus.NOT_RUN,
        "summary",
        "stdout",
        "stderr",
        None,
        (),
        None,
    )


def test_external_tool_type_has_only_required_values():
    assert tuple(item.value for item in ExternalToolType) == (
        "strings",
        "file",
        "exiftool",
        "binwalk",
        "readelf",
        "objdump",
        "nm",
        "openssl",
        "custom",
    )
    assert all(isinstance(item, str) for item in ExternalToolType)


def test_external_tool_status_has_only_required_values_without_running():
    assert tuple(item.value for item in ExternalToolStatus) == (
        "not_run",
        "completed",
        "failed",
        "skipped",
    )
    assert "running" not in {item.value for item in ExternalToolStatus}


def test_base_external_tool_is_abstract_and_declares_only_contract():
    assert inspect.isabstract(BaseExternalTool)
    assert BaseExternalTool.__abstractmethods__ == {"tool_type", "execute"}
    with pytest.raises(TypeError):
        BaseExternalTool()


def test_fake_external_tool_satisfies_contract():
    tool = FakeExternalTool()
    request = ToolRequest(ChallengeInput("question"), None)

    result = tool.execute(request)

    assert tool.tool_type is ExternalToolType.STRINGS
    assert tool.requests == [request]
    assert result.tool_type is tool.tool_type
    assert result.status is ExternalToolStatus.COMPLETED


@pytest.mark.parametrize("confidence", [0, 50, 100, None])
def test_tool_evidence_accepts_confidence_boundaries_and_none(confidence):
    evidence = ToolEvidence("source", "detail", confidence)
    assert evidence.confidence == confidence


@pytest.mark.parametrize("confidence", [-1, 101])
def test_tool_evidence_rejects_out_of_range_confidence(confidence):
    with pytest.raises(ValueError, match="confidence"):
        ToolEvidence("source", "detail", confidence)


def test_tool_evidence_limits_detail_and_is_frozen_slotted():
    evidence = ToolEvidence("source", "x" * 500, None)
    assert not hasattr(evidence, "__dict__")
    with pytest.raises(FrozenInstanceError):
        evidence.detail = "changed"
    with pytest.raises(ValueError, match="detail"):
        replace(evidence, detail="x" * 501)


def test_tool_request_defensively_copies_and_freezes_metadata():
    metadata = {"source": "test"}
    request = ToolRequest(ChallengeInput("question"), Path("missing"), metadata)
    metadata["source"] = "changed"
    metadata["new"] = True

    assert request.working_directory == Path("missing")
    assert request.metadata == {"source": "test"}
    assert isinstance(request.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        request.metadata["source"] = "changed"
    assert not hasattr(request, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.working_directory = None


def test_tool_request_accepts_none_directory_without_existence_check():
    request = ToolRequest(ChallengeInput("question"), None)
    assert request.working_directory is None
    assert request.metadata == {}


def test_tool_request_limits_metadata_to_fifty_keys():
    request = ToolRequest(
        ChallengeInput("question"),
        None,
        {str(index): index for index in range(50)},
    )
    assert len(request.metadata) == 50
    with pytest.raises(ValueError, match="metadata"):
        replace(request, metadata={str(index): index for index in range(51)})


def test_tool_result_accepts_documented_boundaries_and_is_frozen_slotted():
    evidence = tuple(ToolEvidence(str(index), "detail", None) for index in range(50))
    result = ToolResult(
        ExternalToolType.CUSTOM,
        ExternalToolStatus.SKIPPED,
        "s" * 500,
        "o" * 65_536,
        "e" * 65_536,
        None,
        evidence,
        "x" * 500,
    )
    assert len(result.evidence) == 50
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.status = ExternalToolStatus.COMPLETED


@pytest.mark.parametrize(
    ("field", "size", "match"),
    [
        ("summary", 501, "summary"),
        ("stdout", 65_537, "stdout"),
        ("stderr", 65_537, "stderr"),
        ("error_message", 501, "error_message"),
    ],
)
def test_tool_result_rejects_text_values_over_limits(field, size, match):
    with pytest.raises(ValueError, match=match):
        replace(_result(), **{field: "x" * size})


def test_tool_result_rejects_more_than_fifty_evidence_items():
    evidence = tuple(ToolEvidence(str(index), "detail", None) for index in range(51))
    with pytest.raises(ValueError, match="evidence"):
        replace(_result(), evidence=evidence)


def test_contract_modules_have_no_execution_environment_or_app_integration():
    modules = (
        "app.external_tools.tool",
        "app.external_tools.tool_request",
        "app.external_tools.tool_result",
    )
    source = "\n".join(
        inspect.getsource(__import__(module, fromlist=["*"])) for module in modules
    ).casefold()
    for forbidden in (
        "subprocess",
        ".exists(",
        "openai",
        "eventpublisher",
        "controller",
        "coordinator",
        "datetime.now",
        "\nopen(",
    ):
        assert forbidden not in source
