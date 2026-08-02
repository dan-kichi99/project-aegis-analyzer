import tkinter as tk

from app.presentation.tool_budget_presenter import ToolBudgetPresenter
from app.presentation.view_models import ApplicationState, BudgetViewModel


class BudgetView:
    def __init__(self, parent: tk.Misc, presenter: ToolBudgetPresenter) -> None:
        self.presenter = presenter
        self.frame = tk.Frame(parent)
        self.iteration_label = tk.Label(self.frame, text="")
        self.action_label = tk.Label(self.frame, text="")
        self.agent_label = tk.Label(self.frame, text="")
        self.ai_label = tk.Label(self.frame, text="")
        self.local_analysis_label = tk.Label(self.frame, text="")
        self.execution_feedback_label = tk.Label(self.frame, text="")
        self.external_tool_label = tk.Label(self.frame, text="")
        self.elapsed_time_label = tk.Label(self.frame, text="")
        for widget in (
            self.iteration_label,
            self.action_label,
            self.agent_label,
            self.ai_label,
            self.local_analysis_label,
            self.execution_feedback_label,
            self.external_tool_label,
            self.elapsed_time_label,
        ):
            widget.pack(fill="x")
        self.clear()

    def render(self, state: ApplicationState | None) -> None:
        budget = self.presenter.present_budget(state)
        self.clear()
        if budget is not None:
            self._render_budget(budget)

    def clear(self) -> None:
        for label, name in self._labels():
            label.configure(text=f"{name}：未設定")

    def _render_budget(self, budget: BudgetViewModel) -> None:
        values = (
            (budget.iterations_used, budget.iterations_max),
            (budget.actions_used, budget.actions_max),
            (budget.agent_runs_used, budget.agent_runs_max),
            (budget.ai_calls_used, budget.ai_calls_max),
            (budget.local_analyses_used, budget.local_analyses_max),
            (budget.feedbacks_used, budget.feedbacks_max),
            (budget.external_tool_runs_used, budget.external_tool_runs_max),
            (budget.elapsed_seconds, budget.elapsed_seconds_max),
        )
        for (label, name), (used, maximum) in zip(self._labels(), values, strict=True):
            label.configure(text=f"{name}：{used}/{maximum}")

    def _labels(self) -> tuple[tuple[tk.Label, str], ...]:
        return (
            (self.iteration_label, "Iteration"),
            (self.action_label, "Action"),
            (self.agent_label, "Agent"),
            (self.ai_label, "AI"),
            (self.local_analysis_label, "Local Analysis"),
            (self.execution_feedback_label, "Execution Feedback"),
            (self.external_tool_label, "External Tool"),
            (self.elapsed_time_label, "Elapsed Time"),
        )
