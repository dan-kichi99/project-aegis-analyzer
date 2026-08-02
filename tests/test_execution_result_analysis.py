import inspect

import pytest

from app.execution.execution_analysis_result import ExecutionOutputSource
from app.execution.execution_result import ExecutionStatus, PythonExecutionResult
from app.execution.execution_result_analyzer import ExecutionResultAnalyzer
from app.judge.flag_extractor import FlagExtractor
from app.judge.judge_result import JudgeResult
from app.utils.result_formatter import ResultFormatter


def _execution(
    *,
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
    started: bool = True,
    stdout: str = "",
    stderr: str = "",
    exit_code: int | None = 0,
    timed_out: bool = False,
    output_truncated: bool = False,
) -> PythonExecutionResult:
    return PythonExecutionResult(
        status=status,
        started=started,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        timed_out=timed_out,
        duration_seconds=0.01,
        failure_reason=None,
        message="result",
        output_truncated=output_truncated,
        cleanup_succeeded=True,
    )


def _analyze(**changes):
    return ExecutionResultAnalyzer(FlagExtractor()).analyze(_execution(**changes))


@pytest.mark.parametrize("flag", ["FLAG{upper}", "flag{lower}", "CTF{ctf}"])
def test_detects_existing_flag_formats_from_stdout(flag):
    result = _analyze(stdout=f"before {flag} after")

    assert result.primary_flag == flag
    assert result.flag_candidates[0].source is ExecutionOutputSource.STDOUT
    assert result.flag_candidates[0].position == 7


def test_detects_flag_from_stderr():
    result = _analyze(stderr="error FLAG{stderr}")

    assert result.primary_flag == "FLAG{stderr}"
    assert result.flag_candidates[0].source is ExecutionOutputSource.STDERR


def test_stdout_candidates_precede_stderr_candidates():
    result = _analyze(
        stdout="FLAG{stdout}",
        stderr="FLAG{stderr}",
    )

    assert [item.flag for item in result.flag_candidates] == [
        "FLAG{stdout}",
        "FLAG{stderr}",
    ]


def test_multiple_candidates_keep_appearance_order():
    result = _analyze(stdout="CTF{first} text FLAG{second} flag{third}")

    assert [item.flag for item in result.flag_candidates] == [
        "CTF{first}",
        "FLAG{second}",
        "flag{third}",
    ]


def test_duplicates_across_streams_keep_first_stdout_occurrence():
    result = _analyze(
        stdout="FLAG{same} FLAG{same}",
        stderr="FLAG{same}",
    )

    assert len(result.flag_candidates) == 1
    assert result.flag_candidates[0].source is ExecutionOutputSource.STDOUT


def test_case_differences_are_not_deduplicated():
    result = _analyze(stdout="FLAG{same} flag{same}")

    assert [item.flag for item in result.flag_candidates] == [
        "FLAG{same}",
        "flag{same}",
    ]


def test_no_candidate_has_none_primary_flag():
    result = _analyze(stdout="ordinary output")

    assert result.flag_candidates == ()
    assert result.primary_flag is None


@pytest.mark.parametrize(
    ("changes", "successful"),
    [
        ({}, True),
        ({"exit_code": 1}, False),
        ({"status": ExecutionStatus.FAILED, "exit_code": 1}, False),
        (
            {
                "status": ExecutionStatus.TIMED_OUT,
                "timed_out": True,
                "exit_code": None,
            },
            False,
        ),
    ],
)
def test_successful_execution_is_independent_of_flag_candidates(
    changes,
    successful,
):
    result = _analyze(stdout="FLAG{candidate}", **changes)

    assert result.successful_execution is successful
    assert result.primary_flag == "FLAG{candidate}"


@pytest.mark.parametrize(
    ("status", "timed_out"),
    [
        (ExecutionStatus.FAILED, False),
        (ExecutionStatus.TIMED_OUT, True),
    ],
)
def test_failed_and_timed_out_started_output_is_still_analyzed(status, timed_out):
    result = _analyze(
        status=status,
        timed_out=timed_out,
        exit_code=None,
        stdout="FLAG{partial}",
    )

    assert result.primary_flag == "FLAG{partial}"
    assert result.successful_execution is False


def test_not_started_result_is_handled_without_treating_text_as_output():
    result = _analyze(
        status=ExecutionStatus.REJECTED,
        started=False,
        exit_code=None,
        stdout="FLAG{not_executed}",
    )

    assert result.flag_candidates == ()
    assert result.successful_execution is False


def test_analysis_keeps_original_execution_dto_and_truncation_state():
    execution = _execution(
        stdout="original FLAG{kept}",
        stderr="original error",
        output_truncated=True,
    )

    result = ExecutionResultAnalyzer(FlagExtractor()).analyze(execution)

    assert result.execution is execution
    assert result.execution.stdout == "original FLAG{kept}"
    assert result.execution.stderr == "original error"
    assert result.execution.output_truncated is True


def test_flag_extractor_extract_keeps_first_match_behavior():
    extractor = FlagExtractor()

    assert extractor.extract("FLAG{first} CTF{second}") == "FLAG{first}"
    assert extractor.extract("nothing") is None


def test_flag_extractor_extract_all_orders_and_deduplicates_exact_matches():
    extractor = FlagExtractor()

    assert extractor.extract_all(
        "FLAG{one} CTF{two} FLAG{one} flag{one}"
    ) == ("FLAG{one}", "CTF{two}", "flag{one}")


def test_analyzer_uses_injected_existing_flag_extractor():
    extractor = FlagExtractor()
    analyzer = ExecutionResultAnalyzer(extractor)

    assert analyzer._flag_extractor is extractor


def test_formatter_displays_candidates_sources_and_no_correctness_claim():
    result = _analyze(stdout="FLAG{out}", stderr="CTF{err}")

    output = ResultFormatter().format_execution_analysis(result)

    assert "実行出力からFlag候補を検出しました。" in output
    assert "FLAG{out}" in output
    assert "検出元：標準出力" in output
    assert "CTF{err}" in output
    assert "検出元：標準エラー" in output
    assert "正解Flagであることは保証されません。" in output
    assert "正解Flagを取得しました" not in output


def test_formatter_displays_no_candidate_message():
    output = ResultFormatter().format_execution_analysis(_analyze(stdout="none"))

    assert "実行出力からFlag候補は検出されませんでした。" in output
    assert "主要候補：なし" in output


@pytest.mark.parametrize(
    "changes",
    [
        {"status": ExecutionStatus.FAILED, "exit_code": 1},
        {
            "status": ExecutionStatus.TIMED_OUT,
            "timed_out": True,
            "exit_code": None,
        },
    ],
)
def test_formatter_warns_for_unsuccessful_execution(changes):
    output = ResultFormatter().format_execution_analysis(
        _analyze(stdout="FLAG{partial}", **changes)
    )

    assert "実行は正常終了していません。" in output
    assert "途中出力の可能性があります。" in output


def test_formatter_warns_when_output_was_truncated():
    output = ResultFormatter().format_execution_analysis(
        _analyze(output_truncated=True)
    )

    assert "未表示部分に別のFlag候補が存在する可能性があります。" in output


def test_multiple_execution_results_remain_independent():
    analyzer = ExecutionResultAnalyzer(FlagExtractor())

    first = analyzer.analyze(_execution(stdout="FLAG{first}"))
    second = analyzer.analyze(_execution(stdout="FLAG{second}"))

    assert first.primary_flag == "FLAG{first}"
    assert second.primary_flag == "FLAG{second}"


def test_analysis_does_not_modify_judge_result_or_confidence():
    judge_result = JudgeResult(category="Rev", answer="answer", confidence=42)

    _analyze(stdout="FLAG{candidate}")

    assert judge_result.flag is None
    assert judge_result.confidence == 42


def test_analyzer_has_no_execution_file_network_or_submission_operations():
    source = inspect.getsource(ExecutionResultAnalyzer)

    assert "subprocess" not in source
    assert "open(" not in source
    assert "Path(" not in source
    assert "requests" not in source
    assert "submit" not in source.casefold()
