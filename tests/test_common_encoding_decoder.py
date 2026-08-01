from pathlib import Path
from unittest.mock import MagicMock

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.file.common_encoding_decoder import decode_common_encoding
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer


def make_file_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def test_decodes_valid_base64_to_utf8():
    assert (
        decode_common_encoding("RkxBR3tiYXNlNjRfdGVzdH0=")
        == "FLAG{base64_test}"
    )


def test_decodes_valid_hex_to_utf8():
    assert (
        decode_common_encoding("464c41477b6865785f746573747d")
        == "FLAG{hex_test}"
    )


def test_base64_flag_is_added_to_strings():
    encoded = "RkxBR3tiYXNlNjRfdGVzdH0="
    result = StaticFileAnalyzer().analyze(
        make_file_input("base64.txt", encoded.encode())
    )

    assert encoded in result.strings
    assert "FLAG{base64_test}" in result.strings


def test_hex_flag_is_added_to_strings():
    encoded = "464c41477b6865785f746573747d"
    result = StaticFileAnalyzer().analyze(
        make_file_input("hex.txt", encoded.encode())
    )

    assert encoded in result.strings
    assert "FLAG{hex_test}" in result.strings


def test_invalid_base64_is_ignored():
    assert decode_common_encoding("invalid===base64") is None


def test_odd_length_hex_is_ignored():
    assert decode_common_encoding("464c41477") is None


def test_non_hex_characters_are_ignored():
    assert decode_common_encoding("464c414Z") is None


def test_non_utf8_decoded_bytes_are_ignored():
    assert decode_common_encoding("/////w==") is None


def test_original_strings_are_preserved():
    encoded = "RkxBR3tiYXNlNjRfdGVzdH0="
    result = StaticFileAnalyzer().analyze(
        make_file_input(
            "preserved.bin",
            f"original\x00{encoded}".encode(),
        )
    )

    assert "original" in result.strings
    assert encoded in result.strings


def test_duplicate_decoded_results_are_not_added():
    encoded = "RkxBR3tkdXBsaWNhdGV9"
    result = StaticFileAnalyzer().analyze(
        make_file_input(
            "duplicate.bin",
            f"{encoded}\x00{encoded}\x00FLAG{{duplicate}}".encode(),
        )
    )

    assert result.strings.count("FLAG{duplicate}") == 1


def test_decoding_is_not_recursive():
    twice_encoded = "Umt4QlIzdHlaV04xY25OcGRtVmZkR1Z6ZEgwPQ=="
    once_decoded = "RkxBR3tyZWN1cnNpdmVfdGVzdH0="
    result = StaticFileAnalyzer().analyze(
        make_file_input("nested.txt", twice_encoded.encode())
    )

    assert once_decoded in result.strings
    assert "FLAG{recursive_test}" not in result.strings


def test_short_common_word_is_not_decoded():
    assert decode_common_encoding("test") is None


def test_decoded_strings_do_not_exceed_existing_limit():
    content = b"".join(
        f"string_{index:04d}\x00".encode()
        for index in range(200)
    )
    result = StaticFileAnalyzer().analyze(
        make_file_input("limit.bin", content)
    )

    assert len(result.strings) == 200


def test_base64_flag_file_uses_local_fast_path_without_ai(tmp_path: Path):
    encoded_file = tmp_path / "encoded.txt"
    encoded_file.write_text(
        "RkxBR3tiYXNlNjRfbG9jYWxfZmxhZ30=",
        encoding="utf-8",
    )
    analyzer = MagicMock(spec=Analyzer)
    analyzer.analyze.return_value = "Misc"
    controller = MagicMock()
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )

    result = service.solve("Analyze attachment", [encoded_file])

    assert result.flag == "FLAG{base64_local_flag}"
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()
    controller.ai_client.generate.assert_not_called()
