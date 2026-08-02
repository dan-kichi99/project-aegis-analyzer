import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog

from app.presentation.input_models import AnalysisRequest
from app.presentation.input_presenter import AnalysisInputPresenter


class AnalysisInputView:
    def __init__(
        self,
        root: tk.Misc,
        presenter: AnalysisInputPresenter,
        on_analysis_requested: Callable[[AnalysisRequest], None] | None = None,
        on_cancel_requested: Callable[[], None] | None = None,
    ) -> None:
        self.presenter = presenter
        self.on_analysis_requested = on_analysis_requested
        self.on_cancel_requested = on_cancel_requested
        self.state = presenter.initial_state()
        self.frame = tk.Frame(root)
        tk.Label(self.frame, text="問題文").pack(anchor="w")
        self.question_text = tk.Text(self.frame, height=10, width=80)
        self.question_text.pack(fill="both", expand=True)
        tk.Label(self.frame, text="添付ファイル").pack(anchor="w")
        self.file_list = tk.Listbox(self.frame, height=8)
        self.file_list.pack(fill="both", expand=True)
        self.add_button = tk.Button(
            self.frame, text="ファイル追加", command=self.add_files
        )
        self.remove_button = tk.Button(
            self.frame, text="選択削除", command=self.remove_selected
        )
        self.clear_button = tk.Button(
            self.frame, text="すべて削除", command=self.clear_files
        )
        self.prepare_button = tk.Button(
            self.frame, text="解析準備", command=self.prepare_analysis
        )
        self.cancel_button = tk.Button(
            self.frame, text="キャンセル", command=self.cancel_analysis
        )
        for button in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.prepare_button,
            self.cancel_button,
        ):
            button.pack(side="left")
        self.error_label = tk.Label(self.frame, text="", fg="red")
        self.error_label.pack(fill="x")
        self.set_enabled(True)

    def add_files(self) -> None:
        selected = filedialog.askopenfilenames(parent=self.frame)
        if not selected:
            return
        self.state = self.presenter.add_files(
            self.state, tuple(Path(value) for value in selected)
        )
        self._sync_file_list()

    def remove_selected(self) -> None:
        selection = self.file_list.curselection()
        if selection:
            self.state = self.presenter.select_file(self.state, int(selection[0]))
            self.state = self.presenter.remove_selected(self.state)
            self._sync_file_list()

    def clear_files(self) -> None:
        self.state = self.presenter.clear_files(self.state)
        self._sync_file_list()

    def clear(self) -> None:
        self.state = self.presenter.initial_state()
        self.question_text.delete("1.0", tk.END)
        self._sync_file_list()
        self.error_label.configure(text="")

    def set_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self.question_text.configure(state=state)
        self.file_list.configure(state=state)
        for button in (
            self.add_button,
            self.remove_button,
            self.clear_button,
            self.prepare_button,
        ):
            button.configure(state=state)
        self.cancel_button.configure(
            state=tk.DISABLED if enabled else tk.NORMAL
        )

    def cancel_analysis(self) -> None:
        if self.on_cancel_requested is not None:
            self.on_cancel_requested()

    def prepare_analysis(self) -> None:
        question = self.question_text.get("1.0", "end-1c")
        self.state = self.presenter.update_question(self.state, question)
        result = self.presenter.validate(self.state)
        if not result.valid:
            self.error_label.configure(text="\n".join(result.errors))
            return
        self.error_label.configure(text="")
        if self.on_analysis_requested is not None:
            self.on_analysis_requested(result.request)

    def _sync_file_list(self) -> None:
        self.file_list.delete(0, tk.END)
        for path in self.state.file_paths:
            self.file_list.insert(tk.END, path.name)
