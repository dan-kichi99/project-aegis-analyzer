from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from app.presentation import (
    AnalysisInputPresenter,
    AnalysisInputState,
    AnalysisRequest,
    InputValidationResult,
    InputValidationStatus,
)


def _files(tmp_path, count):
    paths = []
    for index in range(count):
        path = (tmp_path / f"file{index}.txt").resolve()
        path.write_text("fixture", encoding="utf-8")
        paths.append(path)
    return tuple(paths)


def test_input_dtos_are_frozen_slotted_and_initial_state_is_empty(tmp_path):
    presenter = AnalysisInputPresenter()
    state = presenter.initial_state()
    request = AnalysisRequest("question", ())
    validation = InputValidationResult(InputValidationStatus.VALID, True, (), request)
    for value in (state, request, validation):
        assert not hasattr(value, "__dict__")
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(next(iter(value.__slots__)), None)
    assert state == AnalysisInputState("", (), None, ())


def test_question_preserves_whitespace_newlines_and_limits():
    presenter = AnalysisInputPresenter()
    question = "  first\nsecond  "
    updated = presenter.update_question(presenter.initial_state(), question)
    assert updated.question == question
    assert len(presenter.update_question(updated, "x" * 20_000).question) == 20_000
    with pytest.raises(ValueError, match="20,000"):
        presenter.update_question(updated, "x" * 20_001)


def test_add_files_preserves_order_deduplicates_and_is_atomic(tmp_path):
    presenter = AnalysisInputPresenter()
    paths = _files(tmp_path, 2)
    initial = presenter.initial_state()
    state = presenter.add_files(initial, (paths[0], paths[1], paths[0]))
    assert state.file_paths == paths
    assert initial.file_paths == ()
    missing = (tmp_path / "missing").resolve()
    with pytest.raises(ValueError, match="見つかりません"):
        presenter.add_files(state, (paths[0], missing))
    assert state.file_paths == paths


def test_file_count_allows_twenty_and_rejects_twenty_one(tmp_path):
    presenter = AnalysisInputPresenter()
    paths = _files(tmp_path, 21)
    state = presenter.add_files(presenter.initial_state(), paths[:20])
    assert len(state.file_paths) == 20
    with pytest.raises(ValueError, match="20"):
        presenter.add_files(state, (paths[20],))


def test_invalid_path_types_relative_directory_missing_and_symlink(tmp_path):
    presenter = AnalysisInputPresenter()
    state = presenter.initial_state()
    directory = tmp_path.resolve()
    missing = (tmp_path / "missing").resolve()
    for value in ("not-path", Path("relative"), directory, missing):
        with pytest.raises(ValueError):
            presenter.add_files(state, (value,))
    target = _files(tmp_path, 1)[0]
    with (
        patch.object(Path, "is_symlink", lambda self: self == target),
        pytest.raises(ValueError, match="シンボリックリンク"),
    ):
        presenter.add_files(state, (target,))


def test_selection_remove_and_clear_are_immutable(tmp_path):
    presenter = AnalysisInputPresenter()
    state = presenter.add_files(presenter.initial_state(), _files(tmp_path, 2))
    selected = presenter.select_file(state, 1)
    assert selected.selected_index == 1
    assert presenter.select_file(selected, None).selected_index is None
    for value in (True, -1, 2):
        with pytest.raises(ValueError):
            presenter.select_file(state, value)
    removed = presenter.remove_selected(selected)
    assert len(removed.file_paths) == 1 and removed.selected_index is None
    assert presenter.remove_selected(state) is state
    cleared = presenter.clear_files(selected)
    assert cleared.file_paths == () and cleared.selected_index is None


@pytest.mark.parametrize(("question", "with_file"), [("question", False), ("", True), ("question", True)])
def test_question_file_or_both_are_valid(tmp_path, question, with_file):
    presenter = AnalysisInputPresenter()
    state = presenter.update_question(presenter.initial_state(), question)
    if with_file:
        state = presenter.add_files(state, _files(tmp_path, 1))
    result = presenter.validate(state)
    assert result.status is InputValidationStatus.VALID
    assert result.valid and result.request is not None
    assert all(path.is_absolute() for path in result.request.file_paths)


@pytest.mark.parametrize("question", ["", "  \n\t"])
def test_empty_effective_input_is_invalid(question):
    presenter = AnalysisInputPresenter()
    result = presenter.validate(
        presenter.update_question(presenter.initial_state(), question)
    )
    assert result.status is InputValidationStatus.INVALID
    assert not result.valid and result.request is None
    assert result.errors == ("問題文または添付ファイルを指定してください。",)


def test_file_deleted_after_add_is_invalid_without_full_path_in_error(tmp_path):
    presenter = AnalysisInputPresenter()
    path = _files(tmp_path, 1)[0]
    state = presenter.add_files(presenter.initial_state(), (path,))
    path.unlink()
    result = presenter.validate(state)
    assert not result.valid
    assert "添付ファイルが見つかりません。" in result.errors
    assert str(path) not in "".join(result.errors)
