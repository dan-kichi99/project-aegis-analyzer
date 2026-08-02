import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock

from app.analyzer.analyzer import Analyzer
from app.challenge.challenge_service import ChallengeService
from app.client.base_client import BaseAIClient
from app.controller.controller import Controller
from app.file.file_input import FileInput
from app.file.file_loader import FileLoader
from app.file.static_file_analyzer import StaticFileAnalyzer
from app.judge.judge_result import JudgeResult
from app.prompt.prompt_manager import PromptManager
from app.utils.result_formatter import ResultFormatter
from tests.test_elf_analyzer import make_elf
from tests.test_pe_analyzer import make_pe

Mode = Literal["structural", "local", "fallback"]


@dataclass(slots=True, frozen=True)
class BenchmarkOutcome:
    name: str
    success: bool
    expected_mode: Mode
    actual_mode: Mode
    exception: str | None = None


@dataclass(slots=True, frozen=True)
class BenchmarkMetrics:
    total_cases: int
    local_solved: int
    ai_fallback: int
    false_solved: int
    exceptions: int
    success_rate: float
    local_solve_rate: float


class RecordingFakeAIClient(BaseAIClient):
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "AIによるフェーズ2ベンチマーク回答"


def _build_service() -> tuple[ChallengeService, RecordingFakeAIClient]:
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
        reason="AIフォールバック",
        hypothesis="追加解析が必要です。",
        next_actions=["解析を継続する"],
        gemini_prompt=None,
    )
    controller = Controller(
        analyzer=analyzer,
        knowledge_retriever=knowledge_retriever,
        prompt_manager=PromptManager(),
        ai_client=ai_client,
        judge=judge,
    )
    return (
        ChallengeService(
            controller=controller,
            analyzer=analyzer,
            file_loader=FileLoader(),
            file_analyzer=StaticFileAnalyzer(),
        ),
        ai_client,
    )


def _file_input(name: str, content: bytes) -> FileInput:
    path = Path(name)
    return FileInput(
        name=name,
        path=path,
        size=len(content),
        extension=path.suffix,
        content=content,
    )


def _png() -> bytes:
    chunk_type = b"IEND"
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 0)
        + chunk_type
        + struct.pack(">I", zlib.crc32(chunk_type))
    )


def _xor(plaintext: str, key: int) -> bytes:
    return bytes(byte ^ key for byte in plaintext.encode())


def _caesar(plaintext: str, shift: int) -> str:
    output: list[str] = []
    for character in plaintext:
        if "A" <= character <= "Z":
            output.append(
                chr((ord(character) - ord("A") + shift) % 26 + ord("A"))
            )
        elif "a" <= character <= "z":
            output.append(
                chr((ord(character) - ord("a") + shift) % 26 + ord("a"))
            )
        else:
            output.append(character)
    return "".join(output)


def _run_file(
    tmp_path: Path,
    name: str,
    content: bytes,
    question: str = "Analyze attachment",
) -> tuple[JudgeResult, RecordingFakeAIClient]:
    path = tmp_path / name
    path.write_bytes(content)
    service, ai_client = _build_service()
    return service.solve(question, [path]), ai_client


def _metrics(outcomes: list[BenchmarkOutcome]) -> BenchmarkMetrics:
    total = len(outcomes)
    successes = sum(outcome.success for outcome in outcomes)
    local_solved = sum(outcome.actual_mode == "local" for outcome in outcomes)
    ai_fallback = sum(outcome.actual_mode == "fallback" for outcome in outcomes)
    false_solved = sum(
        outcome.actual_mode == "local" and outcome.expected_mode != "local"
        for outcome in outcomes
    )
    exceptions = sum(outcome.exception is not None for outcome in outcomes)
    return BenchmarkMetrics(
        total_cases=total,
        local_solved=local_solved,
        ai_fallback=ai_fallback,
        false_solved=false_solved,
        exceptions=exceptions,
        success_rate=successes / total,
        local_solve_rate=local_solved / total,
    )


def test_phase2_integrated_benchmark(tmp_path: Path):
    outcomes: list[BenchmarkOutcome] = []
    fast_prompts: list[list[str]] = []
    fallback_prompts: list[list[str]] = []
    solve_results: list[JudgeResult] = []

    def record(
        name: str,
        expected_mode: Mode,
        operation: Callable[[], bool],
        actual_mode: Mode | None = None,
    ) -> None:
        try:
            success = operation()
            outcomes.append(
                BenchmarkOutcome(
                    name=name,
                    success=success,
                    expected_mode=expected_mode,
                    actual_mode=actual_mode or expected_mode,
                )
            )
        except Exception as error:  # noqa: BLE001 - 例外発生数の集計対象
            outcomes.append(
                BenchmarkOutcome(
                    name=name,
                    success=False,
                    expected_mode=expected_mode,
                    actual_mode=actual_mode or expected_mode,
                    exception=f"{type(error).__name__}: {error}",
                )
            )

    static = StaticFileAnalyzer()
    pe32 = static.analyze(_file_input("x86.exe", make_pe()))
    record(
        "PE32 x86解析",
        "structural",
        lambda: pe32.pe_info is not None
        and pe32.pe_info.format == "PE32"
        and pe32.pe_info.architecture == "x86",
    )
    pe64 = static.analyze(_file_input("x64.exe", make_pe(pe_plus=True)))
    record(
        "PE32+ x86-64解析",
        "structural",
        lambda: pe64.pe_info is not None
        and pe64.pe_info.format == "PE32+"
        and pe64.pe_info.architecture == "x86-64",
    )
    elf32 = static.analyze(_file_input("x86.elf", make_elf(elf64=False)))
    record(
        "ELF32解析",
        "structural",
        lambda: elf32.elf_info is not None
        and elf32.elf_info.elf_class == "ELF32",
    )
    elf64 = static.analyze(_file_input("x64.elf", make_elf()))
    record(
        "ELF64解析",
        "structural",
        lambda: elf64.elf_info is not None
        and elf64.elf_info.elf_class == "ELF64",
    )

    rev_compare = static.analyze(
        _file_input("compare.exe", make_pe() + b"\x00strcmp\x00")
    )
    record(
        "Rev strcmp検出",
        "structural",
        lambda: rev_compare.rev_clues is not None
        and any(clue.value == "strcmp" for clue in rev_compare.rev_clues.clues),
    )
    rev_debug = static.analyze(
        _file_input("debug.elf", make_elf() + b"\x00ptrace\x00")
    )
    record(
        "Rev ptrace検出",
        "structural",
        lambda: rev_debug.rev_clues is not None
        and any(clue.value == "ptrace" for clue in rev_debug.rev_clues.clues),
    )

    xor_result, xor_ai = _run_file(
        tmp_path,
        "xor.bin",
        _xor("FLAG{phase2_xor}", 0x23),
    )
    solve_results.append(xor_result)
    fast_prompts.append(xor_ai.prompts)
    record(
        "単一バイトXOR Flag高速解決",
        "local",
        lambda: xor_result.flag == "FLAG{phase2_xor}" and xor_ai.prompts == [],
    )
    caesar_result, caesar_ai = _run_file(
        tmp_path,
        "rot13.txt",
        _caesar("FLAG{phase2_rot13}", 13).encode(),
    )
    solve_results.append(caesar_result)
    fast_prompts.append(caesar_ai.prompts)
    record(
        "Caesar ROT13 Flag高速解決",
        "local",
        lambda: caesar_result.flag == "FLAG{phase2_rot13}"
        and caesar_ai.prompts == [],
    )

    rsa_flag = "FLAG{x}"
    message = int.from_bytes(rsa_flag.encode(), "big")
    p, q, e = 1_000_000_007, 1_000_000_009, 65_537
    n = p * q
    c = pow(message, e, n)
    rsa_service, rsa_ai = _build_service()
    rsa_result = rsa_service.solve(f"n={n} e={e} c={c} p={p} q={q}")
    solve_results.append(rsa_result)
    fast_prompts.append(rsa_ai.prompts)
    record(
        "RSA p/q指定Flag高速解決",
        "local",
        lambda: rsa_result.flag == rsa_flag and rsa_ai.prompts == [],
    )
    rsa_trial_service, rsa_trial_ai = _build_service()
    rsa_trial = rsa_trial_service.solve("n=3233 e=17 c=2790")
    solve_results.append(rsa_trial)
    fallback_prompts.append(rsa_trial_ai.prompts)
    record(
        "RSA小さいn試し割り",
        "fallback",
        lambda: rsa_trial.flag is None
        and len(rsa_trial_ai.prompts) == 1
        and "復号結果：'A'" in rsa_trial_ai.prompts[0],
    )

    png_tail = static.analyze(
        _file_input("tail.png", _png() + b"PK\x03\x04archive")
    )
    record(
        "PNG末尾ZIP検出",
        "structural",
        lambda: png_tail.appended_data is not None
        and png_tail.appended_data.detected_type == "zip",
    )
    pe_overlay = static.analyze(
        _file_input("overlay.exe", make_pe() + b"\x00overlay")
    )
    record(
        "PE Overlay候補検出",
        "structural",
        lambda: pe_overlay.appended_data is not None
        and pe_overlay.appended_data.container_type == "pe",
    )
    elf_tail = static.analyze(
        _file_input("tail.elf", make_elf() + b"tail")
    )
    record(
        "ELF末尾追加候補検出",
        "structural",
        lambda: elf_tail.appended_data is not None
        and elf_tail.appended_data.container_type == "elf",
    )

    fallback, fallback_ai = _run_file(
        tmp_path,
        "ordinary.txt",
        b"ordinary challenge data",
    )
    solve_results.append(fallback)
    fallback_prompts.append(fallback_ai.prompts)
    record(
        "FlagなしAIフォールバック",
        "fallback",
        lambda: fallback.flag is None and len(fallback_ai.prompts) == 1,
    )
    multi_a = tmp_path / "multi-a.txt"
    multi_b = tmp_path / "multi-b.bin"
    multi_a.write_text("ordinary first input", encoding="utf-8")
    multi_b.write_bytes(b"ordinary second input")
    multi_service, multi_ai = _build_service()
    multi = multi_service.solve("Analyze multiple", [multi_a, multi_b])
    solve_results.append(multi)
    fallback_prompts.append(multi_ai.prompts)
    record(
        "複数ファイル処理",
        "fallback",
        lambda: multi.flag is None
        and len(multi_ai.prompts) == 1
        and all(name in multi_ai.prompts[0] for name in ("multi-a.txt", "multi-b.bin")),
    )

    broken_pe = static.analyze(_file_input("broken.exe", b"MZ\x00"))
    record(
        "壊れたPE安全終了",
        "structural",
        lambda: broken_pe.pe_info is None,
    )
    broken_elf = static.analyze(_file_input("broken.elf", b"\x7fELF\x02"))
    record(
        "壊れたELF安全終了",
        "structural",
        lambda: broken_elf.elf_info is None,
    )
    broken_png = static.analyze(
        _file_input("broken.png", b"\x89PNG\r\n\x1a\nbroken")
    )
    record(
        "壊れた末尾対象安全終了",
        "structural",
        lambda: broken_png.appended_data is None,
    )

    xor_false, xor_false_ai = _run_file(
        tmp_path,
        "xor-noise.bin",
        _xor("Enter password", 0x23),
    )
    solve_results.append(xor_false)
    fallback_prompts.append(xor_false_ai.prompts)
    record(
        "XOR誤候補を未解決維持",
        "fallback",
        lambda: xor_false.flag is None and len(xor_false_ai.prompts) == 1,
    )
    caesar_false, caesar_false_ai = _run_file(
        tmp_path,
        "caesar-noise.txt",
        _caesar("Enter password", 7).encode(),
    )
    solve_results.append(caesar_false)
    fallback_prompts.append(caesar_false_ai.prompts)
    record(
        "Caesar誤候補を未解決維持",
        "fallback",
        lambda: caesar_false.flag is None and len(caesar_false_ai.prompts) == 1,
    )
    incomplete_service, incomplete_ai = _build_service()
    incomplete = incomplete_service.solve("RSA n=3233 only")
    solve_results.append(incomplete)
    fallback_prompts.append(incomplete_ai.prompts)
    record(
        "RSA不足パラメータ安全フォールバック",
        "fallback",
        lambda: incomplete.flag is None and len(incomplete_ai.prompts) == 1,
    )

    formatter = ResultFormatter()
    record(
        "全JudgeResult正常表示",
        "structural",
        lambda: all("Project Aegis 解析結果" in formatter.format(result) for result in solve_results),
    )
    record(
        "高速解決AI呼び出し0回",
        "structural",
        lambda: all(prompts == [] for prompts in fast_prompts),
    )
    record(
        "フォールバックAI呼び出し1回",
        "structural",
        lambda: all(len(prompts) == 1 for prompts in fallback_prompts),
    )
    deterministic_input = _file_input(
        "deterministic.exe",
        make_pe() + b"\x00strcmp\x00overlay",
    )
    record(
        "同一入力の再現性",
        "structural",
        lambda: StaticFileAnalyzer().analyze(deterministic_input)
        == StaticFileAnalyzer().analyze(deterministic_input),
    )

    metrics = _metrics(outcomes)
    failures = [outcome for outcome in outcomes if not outcome.success]
    assert failures == []
    assert metrics.total_cases == 25
    assert metrics.local_solved == 3
    assert metrics.ai_fallback == 6
    assert metrics.false_solved == 0
    assert metrics.exceptions == 0
    assert metrics.success_rate == 1.0
    assert metrics.local_solve_rate == 3 / 25
