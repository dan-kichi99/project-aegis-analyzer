import tkinter as tk

from app.presentation.tool_budget_presenter import ToolBudgetPresenter
from app.presentation.view_models import ApplicationState, ExternalToolViewModel


class ExternalToolView:
    def __init__(self, parent: tk.Misc, presenter: ToolBudgetPresenter) -> None:
        self.presenter = presenter
        self.frame = tk.Frame(parent)
        self.history_list = tk.Listbox(self.frame)
        self.tool_type_label = tk.Label(self.frame, text="")
        self.status_label = tk.Label(self.frame, text="")
        self.target_label = tk.Label(self.frame, text="")
        self.summary_label = tk.Label(self.frame, text="")
        self.exit_code_label = tk.Label(self.frame, text="")
        self.repeated_label = tk.Label(self.frame, text="")
        self.error_label = tk.Label(self.frame, text="", fg="red")
        self.evidence_list = tk.Listbox(self.frame)
        for widget in (
            self.history_list,
            self.tool_type_label,
            self.status_label,
            self.target_label,
            self.summary_label,
            self.exit_code_label,
            self.repeated_label,
            self.error_label,
            self.evidence_list,
        ):
            widget.pack(fill="x")
        self.clear()

    def render(self, state: ApplicationState | None) -> None:
        tools = self.presenter.present_external_tools(state)
        self.clear()
        for tool in tools:
            self.history_list.insert(
                tk.END,
                f"{tool.tool_type} / {tool.status} / {tool.target_name}",
            )
        if tools:
            self._render_detail(tools[0])

    def clear(self) -> None:
        self.history_list.delete(0, tk.END)
        self.tool_type_label.configure(text="外部Tool実行履歴はありません。")
        self.status_label.configure(text="状態：未設定")
        self.target_label.configure(text="対象ファイル：未設定")
        self.summary_label.configure(text="概要：未設定")
        self.exit_code_label.configure(text="終了コード：未設定")
        self.repeated_label.configure(text="重複実行：なし")
        self.error_label.configure(text="")
        self.evidence_list.delete(0, tk.END)

    def _render_detail(self, tool: ExternalToolViewModel) -> None:
        self.tool_type_label.configure(text=f"Tool種類：{tool.tool_type}")
        self.status_label.configure(text=f"状態：{tool.status}")
        self.target_label.configure(text=f"対象ファイル：{tool.target_name}")
        self.summary_label.configure(text=f"概要：{tool.summary}")
        exit_code = tool.exit_code if tool.exit_code is not None else "未設定"
        self.exit_code_label.configure(text=f"終了コード：{exit_code}")
        repeated = "あり" if tool.repeated else "なし"
        self.repeated_label.configure(text=f"重複実行：{repeated}")
        self.error_label.configure(text=f"エラー：{tool.error_message}" if tool.error_message else "")
        self.evidence_list.delete(0, tk.END)
        for evidence in tool.evidence:
            self.evidence_list.insert(tk.END, evidence)
