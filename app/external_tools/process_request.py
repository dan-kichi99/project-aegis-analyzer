from dataclasses import dataclass
from math import isfinite
from pathlib import Path

MAX_PROCESS_ARGUMENTS = 50
MAX_PROCESS_ARGUMENT_CHARACTERS = 4_096
MAX_PROCESS_TIMEOUT_SECONDS = 10.0
MAX_STDOUT_BYTES = 65_536
MAX_STDERR_BYTES = 65_536


@dataclass(slots=True, frozen=True)
class ExternalProcessRequest:
    executable: Path
    arguments: tuple[str, ...]
    working_directory: Path
    timeout_seconds: float = 5.0
    max_stdout_bytes: int = 65_536
    max_stderr_bytes: int = 65_536

    def __post_init__(self) -> None:
        if not isinstance(self.executable, Path) or not self.executable.is_absolute():
            raise ValueError("executableは絶対Pathで指定してください。")
        if (
            not isinstance(self.working_directory, Path)
            or not self.working_directory.is_absolute()
        ):
            raise ValueError("working_directoryは絶対Pathで指定してください。")
        if not isinstance(self.arguments, tuple):
            raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                "argumentsはtupleで指定してください。"
            )
        if len(self.arguments) > MAX_PROCESS_ARGUMENTS:
            raise ValueError("argumentsは最大50件です。")
        for argument in self.arguments:
            if not isinstance(argument, str):
                raise ValueError(  # noqa: TRY004 - DTO入力違反はValueErrorへ統一
                    "argumentsの各要素は文字列で指定してください。"
                )
            if len(argument) > MAX_PROCESS_ARGUMENT_CHARACTERS:
                raise ValueError("1引数は4096文字以内で指定してください。")
            if "\0" in argument:
                raise ValueError("引数にNUL文字を含めることはできません。")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= MAX_PROCESS_TIMEOUT_SECONDS
        ):
            raise ValueError("timeout_secondsは0より大きく10以下で指定してください。")
        self._validate_output_limit(
            self.max_stdout_bytes, "max_stdout_bytes", MAX_STDOUT_BYTES
        )
        self._validate_output_limit(
            self.max_stderr_bytes, "max_stderr_bytes", MAX_STDERR_BYTES
        )

    def _validate_output_limit(self, value: int, name: str, maximum: int) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= maximum
        ):
            raise ValueError(f"{name}は1から{maximum} bytesで指定してください。")
