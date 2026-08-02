import tkinter as tk

from app.gui.agent_result_view import AgentResultView
from app.presentation.view_models import ApplicationState, ResultViewModel


class AnalysisResultView:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = tk.Frame(parent)
        self.solved_label = tk.Label(self.frame, text="")
        self.category_label = tk.Label(self.frame, text="")
        self.confidence_label = tk.Label(self.frame, text="")
        self.flag_candidate_label = tk.Label(self.frame, text="")
        self.warning_label = tk.Label(self.frame, text="", fg="red")
        self.answer_heading = tk.Label(self.frame, text="回答")
        self.answer_text = tk.Text(self.frame, state="disabled")
        self.reason_heading = tk.Label(self.frame, text="理由")
        self.reason_text = tk.Text(self.frame, state="disabled")
        self.next_actions_heading = tk.Label(self.frame, text="次のAction")
        self.next_actions_list = tk.Listbox(self.frame)
        for widget in (
            self.solved_label,
            self.category_label,
            self.confidence_label,
            self.flag_candidate_label,
            self.warning_label,
            self.answer_heading,
            self.answer_text,
            self.reason_heading,
            self.reason_text,
            self.next_actions_heading,
            self.next_actions_list,
        ):
            widget.pack(fill="x")
        self.clear()

    def render(self, result: ResultViewModel | None) -> None:
        self.clear()
        if result is None:
            return
        solved = "解決済み" if result.solved else "未解決"
        confidence = "未設定" if result.confidence is None else f"{result.confidence}%"
        self.solved_label.configure(text=f"解決状態：{solved}")
        self.category_label.configure(text=f"カテゴリ：{result.category}")
        self.confidence_label.configure(text=f"信頼度：{confidence}")
        self.flag_candidate_label.configure(
            text=f"Flag候補：{result.flag_candidate or '候補なし'}"
        )
        self.warning_label.configure(text=result.warning or "")
        self._set_read_only_text(self.answer_text, result.answer)
        self._set_read_only_text(self.reason_text, result.reason)
        for action in result.next_actions:
            self.next_actions_list.insert(tk.END, action)

    def clear(self) -> None:
        self.solved_label.configure(text="解析結果はまだありません")
        self.category_label.configure(text="カテゴリ：未設定")
        self.confidence_label.configure(text="信頼度：未設定")
        self.flag_candidate_label.configure(text="Flag候補：候補なし")
        self.warning_label.configure(text="")
        self._set_read_only_text(self.answer_text, "")
        self._set_read_only_text(self.reason_text, "")
        self.next_actions_list.delete(0, tk.END)

    @staticmethod
    def _set_read_only_text(widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.configure(state="disabled")


class AnalysisResultPanel:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = tk.Frame(parent)
        self.result_view = AnalysisResultView(self.frame)
        self.agent_view = AgentResultView(self.frame)
        self.result_view.frame.pack(fill="both", expand=True)
        self.agent_view.frame.pack(fill="both", expand=True)

    def render(self, state: ApplicationState) -> None:
        self.result_view.render(state.result)
        self.agent_view.render(state.agent)
