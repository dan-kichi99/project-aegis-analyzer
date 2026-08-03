import inspect
import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.challenge.challenge_context_builder import ChallengeContextBuilder
from app.challenge.challenge_input import ChallengeInput
from app.challenge.challenge_service import ChallengeService
from app.file.file_analysis_result import FileAnalysisResult
from app.file.file_input import FileInput
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.file.wav_static_analyzer import (
    WAV_INFO_PREFIX,
    WAV_METADATA_PREFIX,
    WAV_TRAILING_PREFIX,
    WavStaticAnalyzer,
)

_FLAG = "picoCTF{wav_static_ok}"


def _chunk(chunk_id: bytes, data: bytes) -> bytes:
    out = chunk_id + struct.pack("<I", len(data)) + data
    if len(data) % 2 == 1:
        out += b"\x00"
    return out


def _fmt(
    *,
    audio_format: int = 1,
    channels: int = 2,
    sample_rate: int = 44100,
    bits: int = 16,
    byte_rate: int | None = None,
    block_align: int | None = None,
    extra_len: int = 0,
) -> bytes:
    if block_align is None:
        block_align = channels * bits // 8
    if byte_rate is None:
        byte_rate = sample_rate * block_align
    payload = struct.pack(
        "<HHIIHH", audio_format, channels, sample_rate, byte_rate, block_align, bits
    )
    if extra_len:
        payload += struct.pack("<H", 0) + b"\x00" * extra_len
    return _chunk(b"fmt ", payload)


def _data(size: int = 2000) -> bytes:
    return _chunk(b"data", b"\x00\x01" * (size // 2))


def _info_sub(sub_id: bytes, text: bytes) -> bytes:
    value = text + b"\x00"
    out = sub_id + struct.pack("<I", len(value)) + value
    if len(value) % 2 == 1:
        out += b"\x00"
    return out


def _list_info(**fields: bytes) -> bytes:
    payload = b"INFO"
    for key, value in fields.items():
        payload += _info_sub(key.encode("ascii"), value)
    return _chunk(b"LIST", payload)


def _wav(chunks: list[bytes]) -> bytes:
    body = b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


# ---------------------------------------------------------------------------
# 基本
# ---------------------------------------------------------------------------


def test_riff_header_and_wave_identifier_are_recognized():
    content = _wav([_fmt(), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.valid_header is True


def test_riff_declared_size_matches_file_size_for_clean_file():
    content = _wav([_fmt(), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.riff_declared_size == len(content) - 8
    assert result.actual_file_size == len(content)
    assert not any("RIFF宣言サイズ" in w for w in result.warnings)


def test_fmt_is_parsed():
    content = _wav([_fmt(channels=2, sample_rate=44100, bits=16), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.audio_format == 1
    assert result.channel_count == 2
    assert result.sample_rate == 44100
    assert result.bits_per_sample == 16


def test_pcm_format_is_identified():
    content = _wav([_fmt(audio_format=1), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.format_name == "PCM"


def test_ieee_float_format_is_identified():
    content = _wav(
        [
            _fmt(audio_format=3, bits=32, block_align=8, byte_rate=44100 * 8),
            _data(),
        ]
    )
    result = WavStaticAnalyzer().analyze(content)
    assert result.format_name == "IEEE Float"


def test_channel_count_is_extracted():
    content = _wav([_fmt(channels=1, block_align=2, byte_rate=44100 * 2), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.channel_count == 1


def test_sample_rate_is_extracted():
    content = _wav([_fmt(sample_rate=48000, byte_rate=48000 * 4), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.sample_rate == 48000


def test_byte_rate_is_extracted():
    content = _wav([_fmt(), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.byte_rate == 44100 * 4


def test_block_align_is_extracted():
    content = _wav([_fmt(), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.block_align == 4


def test_bits_per_sample_is_extracted():
    content = _wav([_fmt(bits=16), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert result.bits_per_sample == 16


def test_data_chunk_is_detected():
    content = _wav([_fmt(), _data(2000)])
    result = WavStaticAnalyzer().analyze(content)
    data_chunk = next(c for c in result.chunks if c.chunk_id == "data")
    assert data_chunk.actual_size == 2000
    assert "not stored" in data_chunk.detail


def test_duration_is_calculated_from_data_size_and_byte_rate():
    content = _wav([_fmt(), _data(44100 * 4)])
    result = WavStaticAnalyzer().analyze(content)
    assert result.duration_seconds == pytest.approx(1.0, rel=1e-6)


def test_chunk_order_is_preserved():
    content = _wav([_fmt(), _data(), _chunk(b"JUNK", b"pad")])
    result = WavStaticAnalyzer().analyze(content)
    assert [c.chunk_id for c in result.chunks] == ["fmt ", "data", "JUNK"]


def test_odd_sized_chunk_padding_is_handled():
    content = _wav([_fmt(), _data(), _chunk(b"JUNK", b"odd")])
    result = WavStaticAnalyzer().analyze(content)
    junk = next(c for c in result.chunks if c.chunk_id == "JUNK")
    assert junk.declared_size == 3
    assert not junk.truncated


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_list_info_chunk_is_parsed():
    content = _wav([_fmt(), _data(), _list_info(INAM=b"Title")])
    result = WavStaticAnalyzer().analyze(content)
    assert any(item.source == "LIST/INFO" for item in result.metadata_items)


def test_inam_title_is_extracted():
    content = _wav([_fmt(), _data(), _list_info(INAM=b"My Title")])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.key == "INAM")
    assert item.value_preview == "My Title"


def test_iart_artist_is_extracted():
    content = _wav([_fmt(), _data(), _list_info(IART=b"The Artist")])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.key == "IART")
    assert item.value_preview == "The Artist"


def test_icmt_comment_is_extracted():
    content = _wav([_fmt(), _data(), _list_info(ICMT=_FLAG.encode())])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.key == "ICMT")
    assert item.value_preview == _FLAG


def test_isft_software_is_extracted():
    content = _wav([_fmt(), _data(), _list_info(ISFT=b"AegisTool")])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.key == "ISFT")
    assert item.value_preview == "AegisTool"


def test_ikey_keywords_is_extracted():
    content = _wav([_fmt(), _data(), _list_info(IKEY=b"ctf,flag")])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.key == "IKEY")
    assert item.value_preview == "ctf,flag"


def _bext_payload(*, description=b"", originator=b"", version=1) -> bytes:
    payload = description.ljust(256, b"\x00")[:256]
    payload += originator.ljust(32, b"\x00")[:32]
    payload += b"\x00" * 32  # originator_reference
    payload += b"\x00" * 10  # origination_date
    payload += b"\x00" * 8  # origination_time
    payload += b"\x00" * 8  # time_reference
    payload += struct.pack("<H", version)
    return payload


def test_bext_is_parsed():
    content = _wav(
        [_fmt(), _data(), _chunk(b"bext", _bext_payload(description=_FLAG.encode()))]
    )
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.source == "bext")
    assert item.key == "description"
    assert _FLAG in item.value_preview


def test_ixml_is_parsed_without_xml_parser():
    ixml_text = f"<BWFXML><PROJECT>{_FLAG}</PROJECT><SCENE>Scene1</SCENE></BWFXML>"
    content = _wav([_fmt(), _data(), _chunk(b"iXML", ixml_text.encode())])
    result = WavStaticAnalyzer().analyze(content)
    project_item = next(m for m in result.metadata_items if m.key == "PROJECT")
    assert _FLAG in project_item.value_preview
    scene_item = next(m for m in result.metadata_items if m.key == "SCENE")
    assert scene_item.value_preview == "Scene1"


def test_disp_chunk_is_parsed():
    payload = struct.pack("<I", 1) + f"Display {_FLAG}".encode()
    content = _wav([_fmt(), _data(), _chunk(b"DISP", payload)])
    result = WavStaticAnalyzer().analyze(content)
    item = next(m for m in result.metadata_items if m.source == "DISP")
    assert _FLAG in item.value_preview


def _id3_payload(frames: dict[str, bytes]) -> bytes:
    body = b""
    for frame_id, text in frames.items():
        frame_data = b"\x00" + text
        body += frame_id.encode("ascii") + struct.pack(">I", len(frame_data)) + b"\x00\x00" + frame_data
    header = b"ID3" + bytes([3, 0]) + bytes([0])
    size = len(body)
    syncsafe = bytes(
        [
            (size >> 21) & 0x7F,
            (size >> 14) & 0x7F,
            (size >> 7) & 0x7F,
            size & 0x7F,
        ]
    )
    return header + syncsafe + body


def test_id3_presence_is_detected():
    content = _wav([_fmt(), _data(), _chunk(b"id3 ", _id3_payload({"TIT2": b"Song Title"}))])
    result = WavStaticAnalyzer().analyze(content)
    id3_chunk = next(c for c in result.chunks if c.chunk_id == "id3 ")
    assert "ID3v2" in id3_chunk.detail
    tit2_item = next(m for m in result.metadata_items if m.key == "TIT2")
    assert tit2_item.value_preview == "Song Title"


def test_flag_candidates_are_collected_from_metadata():
    content = _wav([_fmt(), _data(), _list_info(ICMT=_FLAG.encode())])
    result = WavStaticAnalyzer().analyze(content)
    assert _FLAG in result.flag_candidates


def test_important_metadata_keys_are_flagged():
    content = _wav(
        [_fmt(), _data(), _list_info(ICMT=b"a comment", ICOP=b"rights", INAM=b"title")]
    )
    result = WavStaticAnalyzer().analyze(content)
    icmt = next(m for m in result.metadata_items if m.key == "ICMT")
    icop = next(m for m in result.metadata_items if m.key == "ICOP")
    assert icmt.important is True
    assert icop.important is True


# ---------------------------------------------------------------------------
# 補助chunk
# ---------------------------------------------------------------------------


def test_fact_chunk_sample_length_is_extracted():
    content = _wav([_fmt(), _data(), _chunk(b"fact", struct.pack("<I", 12345))])
    result = WavStaticAnalyzer().analyze(content)
    fact_chunk = next(c for c in result.chunks if c.chunk_id == "fact")
    assert "sample_length=12345" in fact_chunk.detail


def test_cue_chunk_point_count_is_extracted():
    content = _wav([_fmt(), _data(), _chunk(b"cue ", struct.pack("<I", 3) + b"\x00" * 24 * 3)])
    result = WavStaticAnalyzer().analyze(content)
    cue_chunk = next(c for c in result.chunks if c.chunk_id == "cue ")
    assert "cue_point_count=3" in cue_chunk.detail


def test_smpl_chunk_loop_count_is_extracted():
    smpl_payload = struct.pack("<9I", 0, 0, 0, 0, 0, 0, 0, 2, 8) + b"\x00" * 8
    content = _wav([_fmt(), _data(), _chunk(b"smpl", smpl_payload)])
    result = WavStaticAnalyzer().analyze(content)
    smpl_chunk = next(c for c in result.chunks if c.chunk_id == "smpl")
    assert "loop_count=2" in smpl_chunk.detail


def test_junk_chunk_is_detected():
    content = _wav([_fmt(), _data(), _chunk(b"JUNK", b"filler data")])
    result = WavStaticAnalyzer().analyze(content)
    assert any(c.chunk_id == "JUNK" for c in result.chunks)


def test_unknown_chunk_is_recorded_with_order_and_offset():
    content = _wav([_fmt(), _data(), _chunk(b"XTRA", b"custom vendor data")])
    result = WavStaticAnalyzer().analyze(content)
    unknown_chunk = next(c for c in result.chunks if c.chunk_id == "XTRA")
    assert unknown_chunk.known is False


def test_unknown_chunk_flag_candidate_is_detected():
    content = _wav([_fmt(), _data(), _chunk(b"XTRA", _FLAG.encode())])
    result = WavStaticAnalyzer().analyze(content)
    assert _FLAG in result.flag_candidates


def test_unknown_chunk_magic_is_detected():
    content = _wav([_fmt(), _data(), _chunk(b"XTRA", b"PK\x03\x04 embedded zip")])
    result = WavStaticAnalyzer().analyze(content)
    unknown_chunk = next(c for c in result.chunks if c.chunk_id == "XTRA")
    assert "magic=ZIP" in unknown_chunk.detail


# ---------------------------------------------------------------------------
# 異常系
# ---------------------------------------------------------------------------


def test_missing_riff_header_returns_undetected_result():
    result = WavStaticAnalyzer().analyze(b"not a wav file at all")
    assert result.valid_header is False
    assert result.chunks == ()
    assert result.warnings == ()


def test_missing_wave_identifier_returns_undetected_result():
    content = b"RIFF" + struct.pack("<I", 100) + b"XXXX" + b"\x00" * 96
    result = WavStaticAnalyzer().analyze(content)
    assert result.valid_header is False


def test_riff_size_mismatch_is_reported():
    content = _wav([_fmt(), _data()]) + b"extra appended bytes"
    result = WavStaticAnalyzer().analyze(content)
    assert any("RIFF宣言サイズ" in w for w in result.warnings)


def test_missing_fmt_is_reported():
    content = _wav([_data()])
    result = WavStaticAnalyzer().analyze(content)
    assert "fmtチャンクが見つかりません。" in result.warnings


def test_missing_data_is_reported():
    content = _wav([_fmt()])
    result = WavStaticAnalyzer().analyze(content)
    assert "dataチャンクが見つかりません。" in result.warnings


def test_duplicate_fmt_is_reported():
    content = _wav([_fmt(), _fmt(), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert "fmtチャンクが複数回出現しています。" in result.warnings


def test_multiple_data_chunks_is_reported():
    content = _wav([_fmt(), _data(100), _data(100)])
    result = WavStaticAnalyzer().analyze(content)
    assert "dataチャンクが複数回出現しています。" in result.warnings


def test_truncated_chunk_is_reported():
    content = _wav([_fmt(), _data()])
    content = content[:-10]
    result = WavStaticAnalyzer().analyze(content)
    assert result.truncated is True
    assert any("切り詰められ" in w for w in result.warnings)


def test_chunk_beyond_file_bounds_is_reported():
    body = _fmt() + b"data" + struct.pack("<I", 100_000) + b"short"
    content = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body
    result = WavStaticAnalyzer().analyze(content)
    assert any("ファイル範囲外" in w for w in result.warnings)


def test_missing_padding_is_reported():
    body = _fmt() + _data() + b"JUNK" + struct.pack("<I", 3) + b"odd"
    content = b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body
    result = WavStaticAnalyzer().analyze(content)
    assert any("padding" in w for w in result.warnings)


def test_fmt_length_too_short_is_reported():
    content = _wav([_chunk(b"fmt ", struct.pack("<HHI", 1, 2, 44100)), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert any("fmtチャンクの長さ" in w for w in result.warnings)


def test_channel_count_zero_is_reported():
    content = _wav(
        [_fmt(channels=0, block_align=0, byte_rate=0), _data()]
    )
    result = WavStaticAnalyzer().analyze(content)
    assert "channel_countが0です。" in result.warnings


def test_sample_rate_zero_is_reported():
    content = _wav([_fmt(sample_rate=0, byte_rate=0), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert "sample_rateが0です。" in result.warnings


def test_bits_per_sample_zero_is_reported():
    content = _wav(
        [_fmt(bits=0, block_align=0, byte_rate=0), _data()]
    )
    result = WavStaticAnalyzer().analyze(content)
    assert "bits_per_sampleが0です。" in result.warnings


def test_byte_rate_inconsistency_is_reported():
    payload = struct.pack("<HHIIHH", 1, 2, 44100, 999, 4, 16)
    content = _wav([_chunk(b"fmt ", payload), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert any("byte_rate" in w for w in result.warnings)


def test_block_align_inconsistency_is_reported():
    payload = struct.pack("<HHIIHH", 1, 2, 44100, 176400, 999, 16)
    content = _wav([_chunk(b"fmt ", payload), _data()])
    result = WavStaticAnalyzer().analyze(content)
    assert any("block_align" in w for w in result.warnings)


def test_chunk_count_over_limit_is_truncated():
    filler = [_chunk(b"JUNK", b"x") for _ in range(510)]
    content = _wav([_fmt(), _data(), *filler])
    result = WavStaticAnalyzer().analyze(content)
    assert result.truncated is True
    assert any("chunk数が上限を超えた" in w for w in result.warnings)
    assert len(result.chunks) <= 500


def test_metadata_count_over_limit_is_truncated():
    many_info = b"INFO" + b"".join(
        _info_sub(b"INAM", f"title-{i}".encode()) for i in range(210)
    )
    content = _wav([_fmt(), _data(), _chunk(b"LIST", many_info)])
    result = WavStaticAnalyzer().analyze(content)
    assert len(result.metadata_items) <= 200


# ---------------------------------------------------------------------------
# Trailing Data
# ---------------------------------------------------------------------------


def test_trailing_data_after_valid_chunks_is_detected():
    base = _wav([_fmt(), _data()])
    content = base + b"PK\x03\x04trailing bytes"
    result = WavStaticAnalyzer().analyze(content)
    assert result.trailing_data is not None
    assert result.trailing_data.offset == len(base)


def test_trailing_data_detects_zip_magic():
    content = _wav([_fmt(), _data()]) + b"PK\x03\x04rest of zip"
    result = WavStaticAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "ZIP"


def test_trailing_data_detects_pdf_magic():
    content = _wav([_fmt(), _data()]) + b"%PDF-1.4\nrest of pdf"
    result = WavStaticAnalyzer().analyze(content)
    assert result.trailing_data.detected_magic == "PDF"


def test_trailing_data_extracts_ascii_strings():
    content = _wav([_fmt(), _data()]) + b"\x00\x00hidden_marker_string\x00\x00"
    result = WavStaticAnalyzer().analyze(content)
    assert "hidden_marker_string" in result.trailing_data.strings


def test_trailing_data_extracts_flag_candidates():
    content = _wav([_fmt(), _data()]) + f"junk {_FLAG} junk".encode()
    result = WavStaticAnalyzer().analyze(content)
    assert _FLAG in result.trailing_data.flag_candidates
    assert _FLAG in result.flag_candidates


def test_trailing_data_is_bounded_to_analysis_limit():
    content = _wav([_fmt(), _data()]) + (b"A" * 2_000_000)
    result = WavStaticAnalyzer().analyze(content)
    assert result.trailing_data.truncated is True
    assert result.trailing_data.size == 2_000_000


def test_trailing_data_dto_never_holds_full_content():
    content = _wav([_fmt(), _data()]) + (b"A" * 2_000_000)
    result = WavStaticAnalyzer().analyze(content)
    field_names = set(result.trailing_data.__slots__)
    assert "content" not in field_names
    assert "raw" not in field_names
    assert "data" not in field_names
    assert len(result.trailing_data.preview) <= 500


# ---------------------------------------------------------------------------
# 統合
# ---------------------------------------------------------------------------


def test_static_file_analyzer_adds_reserved_prefixed_wav_strings():
    content = _wav([_fmt(), _data(), _list_info(ICMT=_FLAG.encode())])
    file_input = FileInput("chal.wav", Path("chal.wav"), len(content), ".wav", content)
    result = StaticFileAnalyzer().analyze(file_input)

    info_strings = [s for s in result.strings if s.startswith(WAV_INFO_PREFIX)]
    assert any("format=PCM" in s for s in info_strings)
    metadata_strings = [s for s in result.strings if s.startswith(WAV_METADATA_PREFIX)]
    assert any(_FLAG in s for s in metadata_strings)


def test_context_builder_shows_dedicated_wav_analysis_heading_without_duplication():
    content = _wav([_fmt(), _data()]) + b"PK\x03\x04trailing"
    file_input = FileInput("chal.wav", Path("chal.wav"), len(content), ".wav", content)
    file_result = StaticFileAnalyzer().analyze(file_input)
    challenge = ChallengeInput(question="WAVを解析してください", files=[file_result])

    context = ChallengeContextBuilder().build(challenge)

    assert "WAV Analysis:" in context
    assert "format=PCM" in context
    assert WAV_INFO_PREFIX not in context
    assert WAV_TRAILING_PREFIX not in context


def test_existing_file_analysis_result_dto_is_unchanged():
    result = FileAnalysisResult("x", 0, ".bin", "unknown", None, [])
    assert result.recursive_encoding_result is None


def test_static_file_analyzer_public_constructor_and_analyze_signature_unchanged():
    analyzer = StaticFileAnalyzer()
    signature = inspect.signature(analyzer.analyze)
    assert list(signature.parameters) == ["file_input"]


def test_wav_flag_is_solved_via_existing_strings_fast_path_without_ai(tmp_path: Path):
    content = _wav([_fmt(), _data(), _list_info(ICMT=_FLAG.encode())])
    wav_path = tmp_path / "chal.wav"
    wav_path.write_bytes(content)

    controller = MagicMock()
    analyzer = MagicMock()
    analyzer.analyze.return_value = "Forensics"
    service = ChallengeService(controller=controller, analyzer=analyzer)

    result = service.solve("WAVからFlagを見つけてください", [wav_path])

    assert result.flag == _FLAG
    assert result.confidence == 90
    controller.process_challenge.assert_not_called()


def test_analyzer_source_has_no_forbidden_external_tools_or_execution():
    source = Path("app/file/wav_static_analyzer.py").read_text(encoding="utf-8")
    for forbidden in (
        "subprocess",
        "os.system",
        "eval(",
        "exec(",
        "ffmpeg",
        "ffprobe",
        "sox",
        "librosa",
        "scipy",
        "numpy",
        "pydub",
        "import wave",
        "shell=True",
        "tempfile",
        "NamedTemporaryFile",
        "open(",
    ):
        assert forbidden not in source


def test_file_size_over_fifty_megabytes_is_not_parsed():
    oversized = b"RIFF" + struct.pack("<I", 50_000_002) + b"WAVE" + b"\x00" * 50_000_000
    result = WavStaticAnalyzer().analyze(oversized)
    assert result.valid_header is True
    assert result.truncated is True
    assert result.chunks == ()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), SystemExit()])
def test_keyboard_interrupt_and_system_exit_are_not_swallowed(monkeypatch, error):
    analyzer = WavStaticAnalyzer()
    monkeypatch.setattr(
        analyzer._flag_extractor,
        "extract_all",
        lambda _value: (_ for _ in ()).throw(error),
    )
    with pytest.raises(type(error)):
        analyzer.analyze(_wav([_fmt(), _data(), _list_info(ICMT=b"x")]))


def test_jpeg_png_pdf_archive_and_rev_regression_are_unaffected():
    zip_content = b"PK\x05\x06" + b"\x00" * 18
    zip_input = FileInput("empty.zip", Path("empty.zip"), len(zip_content), ".zip", zip_content)
    zip_result = StaticFileAnalyzer().analyze(zip_input)
    assert zip_result.detected_type == "zip"
    assert not any(s.startswith(WAV_INFO_PREFIX) for s in zip_result.strings)

    png_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    png_input = FileInput("chal.png", Path("chal.png"), len(png_content), ".png", png_content)
    png_result = StaticFileAnalyzer().analyze(png_input)
    assert not any(s.startswith(WAV_INFO_PREFIX) for s in png_result.strings)

    pdf_content = b"%PDF-1.7\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
    pdf_input = FileInput("chal.pdf", Path("chal.pdf"), len(pdf_content), ".pdf", pdf_content)
    pdf_result = StaticFileAnalyzer().analyze(pdf_input)
    assert not any(s.startswith(WAV_INFO_PREFIX) for s in pdf_result.strings)

    jpeg_content = b"\xff\xd8\xff\xd9"
    jpeg_input = FileInput("chal.jpg", Path("chal.jpg"), len(jpeg_content), ".jpg", jpeg_content)
    jpeg_result = StaticFileAnalyzer().analyze(jpeg_input)
    assert not any(s.startswith(WAV_INFO_PREFIX) for s in jpeg_result.strings)

    pe_content = b"MZ" + b"\x00" * 100
    pe_input = FileInput("app.exe", Path("app.exe"), len(pe_content), ".exe", pe_content)
    pe_result = StaticFileAnalyzer().analyze(pe_input)
    assert not any(s.startswith(WAV_INFO_PREFIX) for s in pe_result.strings)
