from dataclasses import replace
from pathlib import Path

from app.presentation.input_models import (
    MAX_INPUT_FILES,
    MAX_QUESTION_CHARACTERS,
    AnalysisInputState,
    AnalysisRequest,
    InputValidationResult,
    InputValidationStatus,
)


class AnalysisInputPresenter:
    def initial_state(self) -> AnalysisInputState:
        return AnalysisInputState("", (), None, ())

    def update_question(
        self, state: AnalysisInputState, question: str
    ) -> AnalysisInputState:
        if len(question) > MAX_QUESTION_CHARACTERS:
            raise ValueError("問題文は20,000文字以内で指定してください。")
        return replace(state, question=question, validation_errors=())

    def add_files(
        self, state: AnalysisInputState, paths: tuple[Path, ...]
    ) -> AnalysisInputState:
        for path in paths:
            self._validate_path(path)
        combined = tuple(dict.fromkeys((*state.file_paths, *paths)))
        if len(combined) > MAX_INPUT_FILES:
            raise ValueError("添付ファイルは最大20件です。")
        return replace(
            state,
            file_paths=combined,
            selected_index=None,
            validation_errors=(),
        )

    def select_file(
        self, state: AnalysisInputState, index: int | None
    ) -> AnalysisInputState:
        if index is None:
            return replace(state, selected_index=None)
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index < len(state.file_paths)
        ):
            raise ValueError("選択位置が範囲外です。")
        return replace(state, selected_index=index)

    def remove_selected(self, state: AnalysisInputState) -> AnalysisInputState:
        if state.selected_index is None:
            return state
        paths = tuple(
            path
            for index, path in enumerate(state.file_paths)
            if index != state.selected_index
        )
        return replace(state, file_paths=paths, selected_index=None, validation_errors=())

    def clear_files(self, state: AnalysisInputState) -> AnalysisInputState:
        return replace(state, file_paths=(), selected_index=None, validation_errors=())

    def validate(self, state: AnalysisInputState) -> InputValidationResult:
        errors: list[str] = []
        if not state.question.strip() and not state.file_paths:
            errors.append("問題文または添付ファイルを指定してください。")
        for path in state.file_paths:
            try:
                self._validate_path(path)
            except ValueError as error:
                message = str(error)
                if message not in errors:
                    errors.append(message)
        if errors:
            return InputValidationResult(
                InputValidationStatus.INVALID,
                False,
                tuple(errors[:20]),
                None,
            )
        request = AnalysisRequest(state.question, state.file_paths)
        return InputValidationResult(InputValidationStatus.VALID, True, (), request)

    def _validate_path(self, path: Path) -> None:
        if not isinstance(path, Path):
            raise ValueError(  # noqa: TRY004 - 入力検証エラーはValueErrorへ統一
                "添付ファイルはPathで指定してください。"
            )
        if not path.is_absolute():
            raise ValueError("添付ファイルは絶対Pathで指定してください。")
        if path.is_symlink():
            raise ValueError("シンボリックリンクは指定できません。")
        if not path.exists():
            raise ValueError("添付ファイルが見つかりません。")
        if not path.is_file():
            raise ValueError("添付ファイルとして通常ファイルを指定してください。")
