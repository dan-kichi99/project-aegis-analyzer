import io
import struct
import zipfile
import zlib
from pathlib import Path
from unittest.mock import MagicMock

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.judge.judge_result import JudgeResult
from app.prompt.prompt_manager import PromptManager
from app.utils.result_formatter import ResultFormatter


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "AIによる通常解析結果"


def build_service() -> tuple[ChallengeService, RecordingFakeAIClient]:
    analyzer = Analyzer()
    ai_client = RecordingFakeAIClient()
    knowledge_retriever = MagicMock()
    knowledge_retriever.retrieve.return_value = []
    judge = MagicMock()
    judge.evaluate.side_effect = lambda category, answer: JudgeResult(
        category=category,
        answer=answer,
        flag=None,
        confidence=50,
        reason="AI解析",
        hypothesis="追加調査が必要です。",
        next_actions=["追加情報を確認する"],
        gemini_prompt=None,
    )
    controller = Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge_retriever,
        prompt_manager=PromptManager(),
        ai_client=ai_client,
        judge=judge,
    )
    service = ChallengeService(
        controller=controller,
        analyzer=analyzer,
        file_loader=FileLoader(),
        file_analyzer=StaticFileAnalyzer(),
    )
    return service, ai_client


def make_zip(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return output.getvalue()


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data))
    )


def make_png_text(value: bytes) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"tEXt", b"Comment\x00" + value)
        + png_chunk(b"IEND", b"")
    )


def solve_file(tmp_path: Path, name: str, content: bytes):
    file_path = tmp_path / name
    file_path.write_bytes(content)
    service, ai_client = build_service()
    result = service.solve("Analyze attachment", [file_path])
    return result, ai_client


def test_plain_text_flag_uses_fast_path_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "flag.txt",
        b"FLAG{plain_text}",
    )

    assert result.flag == "FLAG{plain_text}"
    assert ai_client.prompts == []


def test_base64_flag_flows_through_decoder_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "base64.txt",
        b"RkxBR3twcm9kdWN0aW9uX2I2NH0=",
    )

    assert result.flag == "FLAG{production_b64}"
    assert ai_client.prompts == []


def test_hex_flag_flows_through_decoder_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "hex.txt",
        b"464c41477b70726f64756374696f6e5f6865787d",
    )

    assert result.flag == "FLAG{production_hex}"
    assert ai_client.prompts == []


def test_zip_inner_flag_uses_fast_path_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "flag.zip",
        make_zip([("secret.txt", b"FLAG{zip_production}")]),
    )

    assert result.flag == "FLAG{zip_production}"
    assert ai_client.prompts == []


def test_zip_inner_base64_flag_uses_decoder_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "base64.zip",
        make_zip(
            [("encoded.txt", b"RkxBR3t6aXBfcHJvZHVjdGlvbl9iNjR9")]
        ),
    )

    assert result.flag == "FLAG{zip_production_b64}"
    assert ai_client.prompts == []


def test_png_metadata_flag_uses_fast_path_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "flag.png",
        make_png_text(b"FLAG{png_production}"),
    )

    assert result.flag == "FLAG{png_production}"
    assert ai_client.prompts == []


def test_png_metadata_base64_uses_decoder_without_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "base64.png",
        make_png_text(b"RkxBR3twbmdfcHJvZHVjdGlvbl9iNjR9"),
    )

    assert result.flag == "FLAG{png_production_b64}"
    assert ai_client.prompts == []


def test_flagless_problem_calls_controller_and_ai(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "ordinary.txt",
        b"ordinary challenge data",
    )

    assert result.flag is None
    assert result.answer == "AIによる通常解析結果"
    assert len(ai_client.prompts) == 1


def test_broken_zip_finishes_without_exception(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "broken.zip",
        b"PK\x03\x04broken archive",
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_broken_image_finishes_without_exception(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "broken.png",
        b"\x89PNG\r\n\x1a\nbroken image",
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_large_base64_candidate_finishes_safely(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "large-base64.txt",
        b"A" * 2_000_000,
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_large_hex_candidate_finishes_safely(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "large-hex.txt",
        b"41" * 500_000,
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_zip_bomb_condition_finishes_safely(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "bomb.zip",
        make_zip([("bomb.txt", b"A" * 1_000_000)]),
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1


def test_multiple_zip_png_and_text_inputs_complete_normally(tmp_path: Path):
    zip_path = tmp_path / "input.zip"
    zip_path.write_bytes(make_zip([("inside.txt", b"archive data")]))
    png_path = tmp_path / "input.png"
    png_path.write_bytes(make_png_text(b"image metadata"))
    text_path = tmp_path / "input.txt"
    text_path.write_text("plain data", encoding="utf-8")
    service, ai_client = build_service()

    result = service.solve(
        "Analyze all attachments",
        [zip_path, png_path, text_path],
    )

    assert result.flag is None
    assert len(ai_client.prompts) == 1
    prompt = ai_client.prompts[0]
    for name in ("input.zip", "input.zip::inside.txt", "input.png", "input.txt"):
        assert name in prompt


def test_result_formatter_preserves_final_fast_path_display(tmp_path: Path):
    result, ai_client = solve_file(
        tmp_path,
        "format.txt",
        b"FLAG{formatted_result}",
    )

    output = ResultFormatter().format(result)

    assert "Project Aegis 解析結果" in output
    assert "解決済み" in output
    assert "90%" in output
    assert "Flag候補" in output
    assert "FLAG{formatted_result}" in output
    assert ai_client.prompts == []
