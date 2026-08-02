from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.agents.agent_aggregate_result import AgentAggregateResult
from app.agents.agent_input import AgentInput
from app.agents.agent_plan import AgentCandidate, AgentExecutionPlan
from app.agents.agent_planner import MAX_AGENT_CANDIDATES, AgentPlanner
from app.agents.agent_result import AgentEvidence, AgentResult, AgentStatus, AgentType
from app.agents.agent_result_aggregator import (
    MAX_AGGREGATE_EVIDENCE,
    MAX_AGGREGATE_NEXT_ACTIONS,
    MAX_AGGREGATE_SUMMARY_CHARACTERS,
    AgentResultAggregator,
)
from app.challenge.challenge_input import ChallengeInput
from app.file.file_analysis_result import FileAnalysisResult


def _file(
    name="sample.txt",
    extension=".txt",
    detected_type="text",
    **values,
):
    return FileAnalysisResult(
        name=name,
        size=10,
        extension=extension,
        detected_type=detected_type,
        text_content="text",
        strings=[],
        **values,
    )


def _input(category="Unknown", files=None, rsa_result=None):
    return AgentInput(
        ChallengeInput("question", files or [], rsa_result),
        category,
        "context",
        (),
        {"unchanged": True},
    )


def _plan(*types, primary=0):
    return AgentExecutionPlan(
        "Unknown",
        tuple(
            AgentCandidate(agent_type, 100 - index * 10, "reason", index == primary)
            for index, agent_type in enumerate(types)
        ),
    )


def _result(
    agent_type,
    status=AgentStatus.COMPLETED,
    flag=None,
    confidence=50,
    evidence=(),
    actions=(),
    error=None,
):
    return AgentResult(
        agent_type,
        status,
        "agent summary",
        "answer",
        flag,
        confidence,
        evidence,
        actions,
        error,
    )


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("Crypto", AgentType.CRYPTO),
        ("Rev", AgentType.REV),
        ("Web", AgentType.WEB),
        ("Misc", AgentType.FORENSICS),
        ("Unknown", AgentType.GENERAL),
    ],
)
def test_planner_selects_primary_from_shared_category_mapping(category, expected):
    plan = AgentPlanner().plan(_input(category))

    assert plan.category == category
    assert plan.candidates[0].agent_type is expected
    assert plan.candidates[0].primary
    assert plan.candidates[0].priority == 100
    assert plan.candidates[0].reason


@pytest.mark.parametrize(
    ("challenge_value", "file_value"),
    [
        (object(), None),
        (None, {"xor_result": SimpleNamespace(candidates=(object(),))}),
        (None, {"caesar_result": SimpleNamespace(candidates=(object(),))}),
    ],
)
def test_crypto_structured_results_add_crypto_candidate(challenge_value, file_value):
    files = [_file(**file_value)] if file_value else []
    plan = AgentPlanner().plan(_input(files=files, rsa_result=challenge_value))

    crypto = next(item for item in plan.candidates if item.agent_type is AgentType.CRYPTO)
    assert crypto.priority == 80
    assert not crypto.primary
    assert crypto.reason


@pytest.mark.parametrize(
    "values",
    [
        {"pe_info": object()},
        {"elf_info": object()},
        {"rev_clues": SimpleNamespace(clues=(object(),))},
    ],
)
def test_rev_structured_results_add_rev_candidate(values):
    plan = AgentPlanner().plan(_input(files=[_file(**values)]))

    rev = next(item for item in plan.candidates if item.agent_type is AgentType.REV)
    assert rev.priority == 80
    assert rev.reason


@pytest.mark.parametrize(
    "file_result",
    [
        _file("archive.zip::inside.txt"),
        _file(appended_data=object()),
        _file("image.png", ".png", "png"),
        _file("photo.jpg", ".jpg", "jpeg"),
        _file("document.pdf", ".pdf", "pdf"),
        _file("mystery.bin", ".bin", "unknown"),
        _file("mismatch.bin", ".bin", "text"),
    ],
)
def test_forensics_structured_conditions_add_forensics_candidate(file_result):
    plan = AgentPlanner().plan(_input(files=[file_result]))

    candidate = next(
        item for item in plan.candidates if item.agent_type is AgentType.FORENSICS
    )
    assert candidate.priority in {70, 80}
    assert candidate.reason


def test_multiple_files_add_weak_forensics_candidate():
    plan = AgentPlanner().plan(_input(files=[_file(), _file("other.txt")]))

    candidate = next(
        item for item in plan.candidates if item.agent_type is AgentType.FORENSICS
    )
    assert candidate.priority == 50


def test_candidates_are_unique_sorted_limited_and_primary_first():
    file_result = _file(
        "archive.zip::program.exe",
        ".exe",
        "unknown",
        pe_info=object(),
        xor_result=SimpleNamespace(candidates=(object(),)),
    )

    plan = AgentPlanner().plan(_input(files=[file_result], rsa_result=object()))

    assert len(plan.candidates) == MAX_AGENT_CANDIDATES
    assert plan.candidates[0].primary
    assert len({item.agent_type for item in plan.candidates}) == len(plan.candidates)
    assert plan.candidates[1:] == tuple(
        sorted(
            plan.candidates[1:],
            key=lambda item: (-item.priority, item.agent_type.value),
        )
    )


def test_primary_is_not_added_again_when_it_matches_auxiliary_condition():
    plan = AgentPlanner().plan(_input("Crypto", rsa_result=object()))

    assert [item.agent_type for item in plan.candidates] == [AgentType.CRYPTO]


def test_planner_does_not_mutate_input_or_execute_any_agent():
    agent_input = _input(files=[_file(pe_info=object())])
    original_file = agent_input.challenge.files[0]
    original_values = (
        original_file.name,
        original_file.detected_type,
        original_file.pe_info,
    )

    AgentPlanner().plan(agent_input)

    assert agent_input.challenge.files == [original_file]
    assert (
        original_file.name,
        original_file.detected_type,
        original_file.pe_info,
    ) == original_values
    assert agent_input.category == "Unknown"
    assert dict(agent_input.metadata) == {"unchanged": True}


def test_plan_dto_rejects_too_many_duplicate_or_multiple_primary_candidates():
    candidates = tuple(
        AgentCandidate(agent_type, 50, "reason", False)
        for agent_type in (AgentType.CRYPTO, AgentType.REV, AgentType.WEB, AgentType.GENERAL)
    )
    with pytest.raises(ValueError, match="最大3件"):
        AgentExecutionPlan("x", candidates)
    duplicate = AgentCandidate(AgentType.CRYPTO, 50, "reason", False)
    with pytest.raises(ValueError, match="重複"):
        AgentExecutionPlan("x", (duplicate, duplicate))
    with pytest.raises(ValueError, match="主担当"):
        AgentExecutionPlan(
            "x",
            (
                AgentCandidate(AgentType.CRYPTO, 100, "reason", True),
                AgentCandidate(AgentType.REV, 90, "reason", True),
            ),
        )


def test_zero_results_are_safely_aggregated():
    aggregate = AgentResultAggregator().aggregate(_plan(AgentType.GENERAL), ())

    assert aggregate.results == ()
    assert aggregate.primary_result is None
    assert aggregate.status is AgentStatus.SKIPPED
    assert aggregate.flag_candidates == ()
    assert aggregate.primary_flag is None
    assert aggregate.confidence is None


def test_results_are_reordered_to_plan_and_primary_is_preserved():
    crypto = _result(AgentType.CRYPTO)
    rev = _result(AgentType.REV)

    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV),
        (rev, crypto),
    )

    assert aggregate.results == (crypto, rev)
    assert aggregate.primary_result is crypto
    assert aggregate.status is AgentStatus.COMPLETED


def test_duplicate_and_unplanned_results_are_rejected():
    plan = _plan(AgentType.CRYPTO)
    crypto = _result(AgentType.CRYPTO)
    with pytest.raises(ValueError, match="重複"):
        AgentResultAggregator().aggregate(plan, (crypto, crypto))
    with pytest.raises(ValueError, match="計画にありません"):
        AgentResultAggregator().aggregate(plan, (_result(AgentType.REV),))


def test_failed_primary_falls_back_to_completed_auxiliary_and_keeps_failure():
    failed = _result(AgentType.CRYPTO, AgentStatus.FAILED, error="failure")
    completed = _result(AgentType.REV, flag="FLAG{rev}", confidence=80)

    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV),
        (failed, completed),
    )

    assert aggregate.primary_result is completed
    assert aggregate.results == (failed, completed)
    assert aggregate.status is AgentStatus.COMPLETED
    assert "補助Agent" in aggregate.summary


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((AgentStatus.COMPLETED, AgentStatus.FAILED), AgentStatus.COMPLETED),
        ((AgentStatus.FAILED, AgentStatus.SKIPPED), AgentStatus.FAILED),
        ((AgentStatus.SKIPPED, AgentStatus.SKIPPED), AgentStatus.SKIPPED),
    ],
)
def test_aggregate_status_precedence(statuses, expected):
    plan = _plan(AgentType.CRYPTO, AgentType.REV)
    results = tuple(
        _result(agent_type, status)
        for agent_type, status in zip(
            (AgentType.CRYPTO, AgentType.REV),
            statuses,
            strict=True,
        )
    )
    assert AgentResultAggregator().aggregate(plan, results).status is expected


def test_flags_keep_plan_order_exact_dedup_case_and_conflict_agents():
    results = (
        _result(AgentType.CRYPTO, flag="FLAG{same}", confidence=90),
        _result(AgentType.REV, flag="FLAG{same}", confidence=20),
        _result(AgentType.WEB, flag="flag{same}", confidence=10),
    )
    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV, AgentType.WEB),
        tuple(reversed(results)),
    )

    assert aggregate.flag_candidates == ("FLAG{same}", "flag{same}")
    assert aggregate.primary_flag == "FLAG{same}"
    assert aggregate.confidence == 90
    assert len(aggregate.conflicts) == 1
    assert aggregate.conflicts[0].field == "flag_candidate"
    assert aggregate.conflicts[0].values == aggregate.flag_candidates
    assert aggregate.conflicts[0].agents == (
        AgentType.CRYPTO,
        AgentType.REV,
        AgentType.WEB,
    )


def test_auxiliary_flag_supplies_primary_flag_and_confidence_without_average():
    primary = _result(AgentType.CRYPTO, confidence=20)
    auxiliary = _result(AgentType.REV, flag="FLAG{aux}", confidence=85)

    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV),
        (primary, auxiliary),
    )

    assert aggregate.primary_flag == "FLAG{aux}"
    assert aggregate.confidence == 85


def test_evidence_is_ordered_traced_deduplicated_and_limited():
    repeated = AgentEvidence("source", "detail", 50)
    crypto_evidence = tuple(
        [repeated, repeated]
        + [AgentEvidence(f"source-{index}", "detail", 50) for index in range(40)]
    )
    rev_evidence = (repeated,)
    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV),
        (
            _result(AgentType.REV, evidence=rev_evidence),
            _result(AgentType.CRYPTO, evidence=crypto_evidence),
        ),
    )

    assert len(aggregate.evidence) == MAX_AGGREGATE_EVIDENCE
    assert aggregate.evidence[0].source == "[crypto] source"
    assert sum(item.source == "[crypto] source" for item in aggregate.evidence) == 1
    assert all(len(item.detail) <= 500 for item in aggregate.evidence)


def test_next_actions_are_ordered_deduplicated_and_limited():
    crypto_actions = tuple(["same", "same"] + [f"action-{index}" for index in range(20)])
    aggregate = AgentResultAggregator().aggregate(
        _plan(AgentType.CRYPTO, AgentType.REV),
        (
            _result(AgentType.CRYPTO, actions=crypto_actions),
            _result(AgentType.REV, actions=("rev-action",)),
        ),
    )

    assert len(aggregate.next_actions) == MAX_AGGREGATE_NEXT_ACTIONS
    assert aggregate.next_actions[0] == "same"
    assert aggregate.next_actions.count("same") == 1


def test_summary_is_deterministic_limited_and_does_not_include_answers():
    result = _result(AgentType.CRYPTO, flag="FLAG{x}")
    aggregate = AgentResultAggregator().aggregate(_plan(AgentType.CRYPTO), (result,))

    assert aggregate.summary == (
        "1件の専門Agent結果を統合しました。"
        "完了1件、失敗0件、スキップ0件。"
        "Flag候補1件を検出しました。"
    )
    assert "answer" not in aggregate.summary
    assert len(aggregate.summary) <= MAX_AGGREGATE_SUMMARY_CHARACTERS


def test_aggregate_and_inputs_are_frozen_or_unchanged():
    evidence = AgentEvidence("source", "detail", 50)
    result = _result(AgentType.CRYPTO, evidence=(evidence,), actions=("action",))
    original = deepcopy(result)
    aggregate = AgentResultAggregator().aggregate(_plan(AgentType.CRYPTO), (result,))

    assert result == original
    assert aggregate.results[0] is result
    assert isinstance(aggregate, AgentAggregateResult)
    with pytest.raises(FrozenInstanceError):
        aggregate.status = AgentStatus.FAILED
    assert not hasattr(aggregate, "__dict__")
