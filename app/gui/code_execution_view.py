import tkinter as tk
from collections.abc import Callable

from app.codegen.generated_code_result import GeneratedCodeResult
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.presentation.code_execution_models import (
    CodeApprovalDecision,
    CodeApprovalRequest,
    CodeExecutionRequest,
    ExecutionResultViewModel,
)
from app.presentation.code_execution_presenter import CodeExecutionPresenter


class CodeExecutionView:
    def __init__(
        self,
        parent: tk.Misc,
        presenter: CodeExecutionPresenter,
        on_approval_decision: Callable[[CodeApprovalRequest], None] | None = None,
        on_execution_requested: Callable[[CodeExecutionRequest], None] | None = None,
    ) -> None:
        self.presenter = presenter
        self.on_approval_decision = on_approval_decision
        self.on_execution_requested = on_execution_requested
        self.state = presenter.initial_state()
        self.frame = tk.Frame(parent)
        self.candidate_list = tk.Listbox(self.frame)
        self.candidate_list.bind("<<ListboxSelect>>", self._on_select)
        self.purpose_label = tk.Label(self.frame, text="")
        self.language_label = tk.Label(self.frame, text="")
        self.candidate_status_label = tk.Label(self.frame, text="")
        self.risk_label = tk.Label(self.frame, text="")
        self.parseable_label = tk.Label(self.frame, text="")
        self.syntax_error_label = tk.Label(self.frame, text="")
        self.findings_list = tk.Listbox(self.frame)
        self.code_text = tk.Text(self.frame, state="disabled")
        self.warning_label = tk.Label(
            self.frame,
            text="このコードは完全なサンドボックスでは実行されません。",
            fg="red",
        )
        self.message_label = tk.Label(self.frame, text="")
        self.approve_button = tk.Button(
            self.frame,
            text="承認",
            command=lambda: self._approve(CodeApprovalDecision.APPROVE),
        )
        self.reject_button = tk.Button(
            self.frame,
            text="拒否",
            command=lambda: self._approve(CodeApprovalDecision.REJECT),
        )
        self.defer_button = tk.Button(
            self.frame,
            text="保留",
            command=lambda: self._approve(CodeApprovalDecision.DEFER),
        )
        self.execute_button = tk.Button(
            self.frame, text="実行要求", command=self._request_execution
        )
        self.execution_result_list = tk.Listbox(self.frame)
        self.execution_status_label = tk.Label(self.frame, text="")
        self.exit_code_label = tk.Label(self.frame, text="")
        self.duration_label = tk.Label(self.frame, text="")
        self.timeout_label = tk.Label(self.frame, text="")
        self.truncated_label = tk.Label(self.frame, text="")
        self.cleanup_label = tk.Label(self.frame, text="")
        self.success_label = tk.Label(self.frame, text="")
        self.stdout_text = tk.Text(self.frame, state="disabled")
        self.stderr_text = tk.Text(self.frame, state="disabled")
        self.flag_candidates_list = tk.Listbox(self.frame)
        self.primary_flag_label = tk.Label(self.frame, text="")
        self.execution_warning_label = tk.Label(self.frame, text="", fg="red")
        for widget in (
            self.candidate_list, self.purpose_label, self.language_label,
            self.candidate_status_label, self.risk_label, self.parseable_label,
            self.syntax_error_label, self.findings_list, self.code_text,
            self.warning_label, self.message_label, self.approve_button,
            self.reject_button, self.defer_button, self.execute_button,
            self.execution_result_list, self.execution_status_label,
            self.exit_code_label, self.duration_label, self.timeout_label,
            self.truncated_label, self.cleanup_label, self.success_label,
            self.stdout_text, self.stderr_text, self.flag_candidates_list,
            self.primary_flag_label, self.execution_warning_label,
        ):
            widget.pack(fill="x")
        self._sync_candidates()
        self._sync_execution_results()

    def render_candidates(self, generated_code: GeneratedCodeResult | None) -> None:
        self.state = self.presenter.present_candidates(generated_code)
        self._sync_candidates()
        self._sync_execution_results()

    def render_execution_results(
        self, analyses: tuple[ExecutionAnalysisResult, ...]
    ) -> None:
        self.state = self.presenter.present_execution_results(self.state, analyses)
        self._sync_execution_results()

    def clear(self) -> None:
        self.state = self.presenter.initial_state()
        self._sync_candidates()
        self._sync_execution_results()

    def _on_select(self, _event=None) -> None:
        selection = self.candidate_list.curselection()
        index = int(selection[0]) if selection else None
        self.state = self.presenter.select_candidate(self.state, index)
        self._sync_candidate_details()

    def _approve(self, decision: CodeApprovalDecision) -> None:
        try:
            request = self.presenter.build_approval_request(self.state, decision)
        except ValueError:
            return
        if self.on_approval_decision is not None:
            self.on_approval_decision(request)

    def _request_execution(self) -> None:
        try:
            request = self.presenter.build_execution_request(self.state)
        except ValueError:
            return
        if self.on_execution_requested is not None:
            self.on_execution_requested(request)

    def _sync_candidates(self) -> None:
        self.candidate_list.delete(0, tk.END)
        for item in self.state.candidates:
            purpose = item.purpose or "目的未設定"
            self.candidate_list.insert(
                tk.END,
                f"[{item.source_index}] {item.language} / {item.status} / "
                f"{item.risk_level} / {purpose}",
            )
        self._sync_candidate_details()

    def _sync_candidate_details(self) -> None:
        item = self.state.selected_candidate
        self.purpose_label.configure(text=f"目的：{item.purpose or '未設定'}" if item else "目的：未選択")
        self.language_label.configure(text=f"言語：{item.language}" if item else "言語：未選択")
        self.candidate_status_label.configure(text=f"状態：{item.status}" if item else "状態：未選択")
        self.risk_label.configure(text=f"危険度：{item.risk_level}" if item else "危険度：未選択")
        self.parseable_label.configure(text=f"構文解析可能：{'はい' if item and item.parseable else 'いいえ'}")
        self.syntax_error_label.configure(text=f"構文エラー：{item.syntax_error or 'なし'}" if item else "構文エラー：なし")
        self.findings_list.delete(0, tk.END)
        if item is not None:
            for finding in item.findings:
                self.findings_list.insert(tk.END, finding)
        self._set_read_only_text(self.code_text, item.code if item else "")
        self.message_label.configure(text=self.state.message)
        self._set_button(self.approve_button, bool(item and item.can_approve))
        self._set_button(self.reject_button, bool(item and item.can_reject))
        self._set_button(self.defer_button, bool(item and item.can_defer))
        self._set_button(self.execute_button, bool(item and item.can_execute))

    def _sync_execution_results(self) -> None:
        self.execution_result_list.delete(0, tk.END)
        for item in self.state.execution_results:
            self.execution_result_list.insert(tk.END, f"[{item.source_index}] {item.status}")
        item = self.state.execution_results[0] if self.state.execution_results else None
        self._render_execution_detail(item)

    def _render_execution_detail(self, item: ExecutionResultViewModel | None) -> None:
        self.execution_status_label.configure(text=f"実行状態：{item.status}" if item else "実行結果はありません。")
        exit_code = item.exit_code if item and item.exit_code is not None else "未設定"
        self.exit_code_label.configure(text=f"終了コード：{exit_code}")
        self.duration_label.configure(text=f"実行時間：{item.duration_seconds}秒" if item else "実行時間：未設定")
        self.timeout_label.configure(text=f"タイムアウト：{'あり' if item and item.timed_out else 'なし'}")
        self.truncated_label.configure(text=f"出力省略：{'あり' if item and item.output_truncated else 'なし'}")
        self.cleanup_label.configure(text=f"一時領域削除：{'成功' if item and item.cleanup_succeeded else '未確認'}")
        self.success_label.configure(text=f"正常終了：{'はい' if item and item.successful_execution else 'いいえ'}")
        self._set_read_only_text(self.stdout_text, item.stdout if item else "")
        self._set_read_only_text(self.stderr_text, item.stderr if item else "")
        self.flag_candidates_list.delete(0, tk.END)
        if item is not None:
            for flag in item.flag_candidates:
                self.flag_candidates_list.insert(tk.END, flag)
        self.primary_flag_label.configure(text=f"主要Flag候補：{item.primary_flag or '候補なし'}" if item else "主要Flag候補：候補なし")
        self.execution_warning_label.configure(text=item.warning if item else "")

    @staticmethod
    def _set_button(widget: tk.Button, enabled: bool) -> None:
        widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)

    @staticmethod
    def _set_read_only_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.configure(state="disabled")
