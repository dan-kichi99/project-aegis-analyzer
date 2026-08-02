import tkinter as tk

from app.presentation.view_models import AgentViewModel


class AgentResultView:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = tk.Frame(parent)
        self.primary_agent_label = tk.Label(self.frame, text="")
        self.executed_agents_label = tk.Label(self.frame, text="")
        self.status_label = tk.Label(self.frame, text="")
        self.confidence_label = tk.Label(self.frame, text="")
        self.fallback_label = tk.Label(self.frame, text="")
        self.flag_candidates_heading = tk.Label(self.frame, text="Flag候補")
        self.flag_candidates_list = tk.Listbox(self.frame)
        self.evidence_heading = tk.Label(self.frame, text="Evidence")
        self.evidence_list = tk.Listbox(self.frame)
        self.conflicts_heading = tk.Label(self.frame, text="候補競合")
        self.conflicts_list = tk.Listbox(self.frame)
        for widget in (
            self.primary_agent_label,
            self.executed_agents_label,
            self.status_label,
            self.confidence_label,
            self.fallback_label,
            self.flag_candidates_heading,
            self.flag_candidates_list,
            self.evidence_heading,
            self.evidence_list,
            self.conflicts_heading,
            self.conflicts_list,
        ):
            widget.pack(fill="x")
        self.clear()

    def render(self, agent: AgentViewModel | None) -> None:
        self.clear()
        if agent is None:
            return
        self.primary_agent_label.configure(
            text=f"主担当Agent：{agent.primary_agent or '未設定'}"
        )
        executed = "、".join(agent.executed_agents) or "なし"
        self.executed_agents_label.configure(text=f"実行Agent：{executed}")
        self.status_label.configure(text=f"状態：{agent.status}")
        confidence = "未設定" if agent.confidence is None else f"{agent.confidence}%"
        self.confidence_label.configure(text=f"信頼度：{confidence}")
        fallback = "fallback使用" if agent.used_fallback else "fallbackなし"
        self.fallback_label.configure(text=fallback)
        self._replace_items(
            self.flag_candidates_list, agent.flag_candidates or ("候補なし",)
        )
        self._replace_items(self.evidence_list, agent.evidence)
        self._replace_items(self.conflicts_list, agent.conflicts)

    def clear(self) -> None:
        self.primary_agent_label.configure(text="専門Agent結果はありません")
        self.executed_agents_label.configure(text="実行Agent：なし")
        self.status_label.configure(text="状態：未設定")
        self.confidence_label.configure(text="信頼度：未設定")
        self.fallback_label.configure(text="fallbackなし")
        for widget in (
            self.flag_candidates_list,
            self.evidence_list,
            self.conflicts_list,
        ):
            widget.delete(0, tk.END)

    @staticmethod
    def _replace_items(widget: tk.Listbox, items: tuple[str, ...]) -> None:
        widget.delete(0, tk.END)
        for item in items:
            widget.insert(tk.END, item)
