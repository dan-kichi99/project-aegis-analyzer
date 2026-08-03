import re
from dataclasses import dataclass

from app.file.rev_clue_result import RevClue, RevClueResult
from app.judge.flag_extractor import FlagExtractor

_MAX_CLUES = 50
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(slots=True, frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    category: str
    description: str
    severity: str
    preserve_source: bool = False


def _identifier_rule(
    value: str,
    category: str,
    description: str,
    severity: str,
) -> _Rule:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(value)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    return _Rule(pattern, category, description, severity)


def _phrase_rule(
    phrase: str,
    category: str,
    description: str,
    severity: str,
) -> _Rule:
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(phrase)}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )
    return _Rule(pattern, category, description, severity, True)


_GROUPS = (
    (
        ("strcmp", "strncmp", "memcmp", "wcscmp", "CompareStringA", "CompareStringW"),
        "比較処理",
        "入力値や復号結果を期待値と比較している可能性があります。",
        "high",
    ),
    (
        ("scanf", "sscanf", "fscanf", "gets", "fgets", "getchar", "read", "ReadFile", "GetCommandLineA", "GetCommandLineW", "argv", "stdin"),
        "入力処理",
        "ユーザー入力や外部データの取得に関連する可能性があります。",
        "medium",
    ),
    (
        ("printf", "puts", "putchar", "fprintf", "write", "WriteFile", "MessageBoxA", "MessageBoxW", "stdout", "stderr"),
        "出力処理",
        "結果やメッセージの出力に関連する可能性があります。",
        "low",
    ),
    (
        ("fopen", "fclose", "fread", "fwrite", "open", "close", "CreateFileA", "CreateFileW", "DeleteFileA", "DeleteFileW", "GetFileSize"),
        "ファイル操作",
        "ファイルの読み書きや状態確認に関連する可能性があります。",
        "low",
    ),
    (
        ("malloc", "calloc", "realloc", "free", "memcpy", "memmove", "memset"),
        "メモリ操作",
        "メモリ確保やデータ操作に関連する可能性があります。",
        "low",
    ),
    (
        ("VirtualAlloc", "VirtualProtect", "HeapAlloc"),
        "メモリ操作",
        "実行時のメモリ管理を優先確認する手掛かりです。",
        "medium",
    ),
    (
        ("system", "execve", "CreateProcessA", "CreateProcessW", "ShellExecuteA", "ShellExecuteW", "LoadLibraryA", "LoadLibraryW", "GetProcAddress"),
        "プロセス・実行",
        "プロセス起動や動的コード利用に関連する可能性があります。",
        "medium",
    ),
    (
        ("IsDebuggerPresent", "CheckRemoteDebuggerPresent", "NtQueryInformationProcess", "ptrace", "DebugActiveProcess", "OutputDebugStringA", "OutputDebugStringW"),
        "アンチデバッグ",
        "アンチデバッグ処理に利用される可能性があります。",
        "high",
    ),
    (
        ("AES", "RSA", "SHA1", "SHA256", "SHA512", "MD5", "EVP_Encrypt", "EVP_Decrypt", "CryptEncrypt", "CryptDecrypt", "BCryptEncrypt", "BCryptDecrypt", "XOR"),
        "暗号・ハッシュ",
        "暗号化、復号、ハッシュ計算に関連する可能性があります。",
        "medium",
    ),
    (
        ("socket", "connect", "send", "recv", "bind", "listen", "accept", "InternetOpenA", "InternetOpenW", "InternetConnectA", "InternetConnectW", "HttpSendRequestA", "HttpSendRequestW", "WinHttpOpen"),
        "ネットワーク",
        "ネットワーク通信を行う処理に関連する可能性があります。",
        "medium",
    ),
)

_RULES = tuple(
    _identifier_rule(value, category, description, severity)
    for values, category, description, severity in _GROUPS
    for value in values
) + tuple(
    _phrase_rule(
        phrase,
        "成功・失敗メッセージ",
        "入力判定の成功または失敗を示すメッセージの可能性があります。",
        "high" if phrase in {"correct", "success", "accepted", "congratulations", "access granted"} else "medium",
    )
    for phrase in (
        "correct", "success", "accepted", "congratulations", "access granted",
        "wrong", "incorrect", "failed", "denied", "try again", "invalid",
    )
) + tuple(
    _phrase_rule(
        phrase,
        "秘密情報関連",
        "パスワード、鍵、Flagなどの検証処理に関連する可能性があります。",
        "medium",
    )
    for phrase in (
        "password", "passphrase", "secret", "key", "token", "flag",
        "username", "license", "serial",
    )
) + (
    _phrase_rule(
        "/bin/sh",
        "その他の注目文字列",
        "実行時の重要な文字列として優先確認候補です。",
        "medium",
    ),
    _phrase_rule(
        "cmd.exe",
        "その他の注目文字列",
        "実行時の重要な文字列として優先確認候補です。",
        "medium",
    ),
)

_STATIC_RULES = tuple(
    _identifier_rule(value, category, description, severity)
    for values, category, description, severity in (
        (
            (
                "CreateFile",
                "ReadFile",
                "WriteFile",
                "WinExec",
                "ShellExecute",
                "fork",
            ),
            "Import / Export候補",
            "実行ファイルのImportまたはExport候補となる識別子です。",
            "medium",
        ),
        (
            (
                ".text",
                ".data",
                ".rdata",
                ".rodata",
                ".bss",
                ".idata",
                ".eh_frame",
                ".pydata",
                ".upx",
            ),
            "Section",
            "既知の実行ファイルSection名です。",
            "low",
        ),
        (
            ("GCC", "MSVC", "clang", "Rust", "Nuitka", "UPX"),
            "Compiler / Packer",
            "Compiler、runtime、またはpackerの痕跡です。",
            "medium",
        ),
        (
            ("PDB", "debug_assert", "assertion_failed"),
            "デバッグ文字列",
            "デバッグ情報またはassertionの痕跡です。",
            "medium",
        ),
    )
    for value in values
) + tuple(
    _phrase_rule(
        value,
        "Compiler / Packer",
        "Compiler、runtime、またはbundleの痕跡です。",
        "medium",
    )
    for value in (
        "Go build",
        "runtime.main",
        "rust_eh_personality",
        "PyInstaller",
    )
)


class RevClueAnalyzer:
    """実行ファイル由来stringsからRev調査候補を分類する。"""

    def analyze(self, strings: list[str]) -> RevClueResult:
        flag_extractor = FlagExtractor()
        matches: list[tuple[int, int, RevClue]] = []
        seen: dict[tuple[str, str], int] = {}
        for source_index, source in enumerate(strings):
            for rule_index, rule in enumerate((*_RULES, *_STATIC_RULES)):
                match = rule.pattern.search(source)
                if match is None:
                    continue
                value = source.strip() if rule.preserve_source else match.group(0)
                key = (value.casefold(), rule.category)
                if not value:
                    continue
                candidate = (
                    source_index,
                    rule_index,
                    RevClue(
                        value=value,
                        category=rule.category,
                        description=rule.description,
                        severity=rule.severity,
                    ),
                )
                duplicate_index = seen.get(key)
                if duplicate_index is None:
                    seen[key] = len(matches)
                    matches.append(candidate)
                elif (
                    _SEVERITY_ORDER[rule.severity]
                    < _SEVERITY_ORDER[matches[duplicate_index][2].severity]
                ):
                    matches[duplicate_index] = candidate
            for flag in flag_extractor.extract_all(source):
                key = (flag.casefold(), "秘密情報関連")
                candidate = (
                    source_index,
                    len(_RULES) + len(_STATIC_RULES),
                    RevClue(
                        value=flag,
                        category="秘密情報関連",
                        description="既存FlagExtractorが認識したFlag候補です。",
                        severity="high",
                    ),
                )
                duplicate_index = seen.get(key)
                if duplicate_index is None:
                    seen[key] = len(matches)
                    matches.append(candidate)
                elif matches[duplicate_index][2].severity != "high":
                    matches[duplicate_index] = candidate
        matches.sort(
            key=lambda item: (
                _SEVERITY_ORDER[item[2].severity],
                item[0],
                item[1],
            )
        )
        return RevClueResult(
            clues=tuple(item[2] for item in matches[:_MAX_CLUES])
        )
