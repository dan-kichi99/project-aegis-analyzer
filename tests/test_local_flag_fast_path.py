from unittest.mock import MagicMock

import pytest

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.controller.controller import Controller
from app.file.file_analysis_result import FileAnalysisResult
from app.judge.judge_result import JudgeResult


def make_file_result(
    name: str = "sample.txt",
    text_content: str | None = None,
    strings: list[str] | None = None,
) -> FileAnalysisResult:
    return FileAnalysisResult(
        name=name,
        size=100,
        extension=".txt",
        detected_type="text",
        text_content=text_content,
        strings=strings or [],
    )


def make_service(
    analysis_results: list[FileAnalysisResult] | None = None,
    analyzer: Analyzer | None = None,
) -> tuple[ChallengeService, MagicMock, MagicMock, MagicMock]:
    controller = MagicMock()
    if analyzer is None:
        injected_analyzer = MagicMock(spec=Analyzer)
        injected_analyzer.analyze.return_value = "Crypto"
    else:
        injected_analyzer = analyzer
    controller.analyzer = injected_analyzer
    file_loader = MagicMock()
    file_analyzer = MagicMock()
    if analysis_results is not None:
        file_analyzer.analyze.side_effect = analysis_results

    service = ChallengeService(
        controller=controller,
        analyzer=injected_analyzer,
        file_loader=file_loader,
        file_analyzer=file_analyzer,
    )
    return service, controller, file_loader, file_analyzer


def test_text_content_flag_uses_fast_path():
    file_result = make_file_result(
        name="sample.txt",
        text_content="answer: FLAG{text_content_flag}",
    )
    service, controller, _, _ = make_service([file_result])

    result = service.solve("RSA challenge", ["sample.txt"])

    assert result.flag == "FLAG{text_content_flag}"
    assert "sample.txt" in result.reason
    assert "テキスト内容" in result.reason
    controller.process_challenge.assert_not_called()


def test_extracted_strings_flag_uses_fast_path():
    file_result = make_file_result(
        name="challenge.exe",
        strings=["noise", "flag{extracted_string_flag}"],
    )
    service, controller, _, _ = make_service([file_result])

    result = service.solve("Reverse challenge", ["challenge.exe"])

    assert result.flag == "flag{extracted_string_flag}"
    assert "challenge.exe" in result.reason
    assert "抽出文字列" in result.reason
    controller.process_challenge.assert_not_called()


def test_question_flag_example_does_not_use_fast_path():
    service, controller, _, _ = make_service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("Flag format example: FLAG{example}", [])

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_fast_path_does_not_call_ai_generate():
    file_result = make_file_result(
        strings=["flag{no_api_call}"],
    )
    service, controller, _, _ = make_service([file_result])

    service.solve("Find answer", ["sample.txt"])

    controller.ai_client.generate.assert_not_called()
    controller.process_challenge.assert_not_called()


def test_fast_path_returns_complete_solved_result():
    file_result = make_file_result(
        text_content="flag{complete_result}",
    )
    service, _, _, _ = make_service([file_result])

    result = service.solve("RSA challenge", ["sample.txt"])

    assert result.category == "Crypto"
    assert result.answer == "添付ファイル内からFlag候補を検出しました。"
    assert result.confidence == 90
    assert result.hypothesis is None
    assert result.next_actions == []
    assert result.gemini_prompt is None


def test_no_flag_delegates_to_existing_controller_pipeline():
    service, controller, _, _ = make_service()
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("No flag here", [])

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_question_flag_with_flagless_file_delegates_to_controller():
    file_result = make_file_result(
        text_content="No answer in this file",
        strings=["ordinary string"],
    )
    service, controller, _, _ = make_service([file_result])
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve(
        "Example format is CTF{not_the_answer}",
        ["sample.txt"],
    )

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_flag_in_later_file_is_detected():
    files = [
        make_file_result(name="first.txt", text_content="nothing"),
        make_file_result(
            name="second.txt",
            text_content="CTF{later_file_flag}",
        ),
    ]
    service, controller, _, _ = make_service(files)

    result = service.solve("Find answer", ["first.txt", "second.txt"])

    assert result.flag == "CTF{later_file_flag}"
    assert "second.txt" in result.reason
    controller.process_challenge.assert_not_called()


def test_flag_like_text_not_recognized_by_extractor_is_not_fast_path():
    file_result = make_file_result(
        text_content="FLAG-no-braces and key{not_supported}",
    )
    service, controller, _, _ = make_service([file_result])
    expected = object()
    controller.process_challenge.return_value = expected

    result = service.solve("Find answer", ["sample.txt"])

    assert result is expected
    controller.process_challenge.assert_called_once()


def test_file_not_found_error_is_preserved():
    service, controller, file_loader, _ = make_service()
    file_loader.load.side_effect = FileNotFoundError(
        "File not found: missing.txt"
    )

    with pytest.raises(
        FileNotFoundError,
        match="File not found: missing.txt",
    ):
        service.solve("flag{question_flag}", ["missing.txt"])

    controller.process_challenge.assert_not_called()


def test_first_flag_in_existing_search_order_is_returned():
    file_result = make_file_result(
        text_content="FLAG{first} FLAG{second}",
        strings=["FLAG{third}"],
    )
    service, _, _, _ = make_service([file_result])

    result = service.solve("Find answer", ["sample.txt"])

    assert result.flag == "FLAG{first}"


def test_injected_analyzer_is_used_by_fast_path():
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    file_result = make_file_result(text_content="FLAG{injected_analyzer}")
    service, _, _, _ = make_service([file_result], analyzer=analyzer)

    result = service.solve("image forensics", ["sample.txt"])

    assert result.category == "Misc"
    analyzer.analyze.assert_called_once_with("image forensics")


def test_controller_and_service_share_same_analyzer_instance():
    analyzer = MagicMock(spec=Analyzer)
    service, controller, _, _ = make_service(analyzer=analyzer)

    assert controller.analyzer is analyzer
    assert service._analyzer is analyzer


def test_fast_and_normal_paths_use_same_analyzer():
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Crypto"
    knowledge_retriever = MagicMock()
    knowledge_retriever.retrieve.return_value = []
    prompt_manager = MagicMock()
    prompt_manager.build.return_value = "prompt"
    ai_client = MagicMock()
    ai_client.generate.return_value = "normal response"
    judge = MagicMock()
    judge.evaluate.side_effect = lambda category, answer: JudgeResult(
        category=category,
        answer=answer,
    )
    controller = Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge_retriever,
        prompt_manager=prompt_manager,
        ai_client=ai_client,
        judge=judge,
    )

    fast_file_analyzer = MagicMock()
    fast_file_analyzer.analyze.return_value = make_file_result(
        text_content="FLAG{fast_path}",
    )
    fast_service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=MagicMock(),
        file_analyzer=fast_file_analyzer,
    )
    normal_file_analyzer = MagicMock()
    normal_file_analyzer.analyze.return_value = make_file_result(
        text_content="no flag",
    )
    normal_service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=MagicMock(),
        file_analyzer=normal_file_analyzer,
    )

    fast_result = fast_service.solve("RSA challenge", ["fast.txt"])
    normal_result = normal_service.solve("RSA challenge", ["normal.txt"])

    assert fast_service._analyzer is controller.analyzer
    assert normal_service._analyzer is controller.analyzer
    assert fast_result.category == normal_result.category == "Crypto"
    assert analyzer.analyze.call_count == 2
