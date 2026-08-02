import tkinter as tk
from collections.abc import Callable

from app.codegen.generated_code_result import GeneratedCodeResult
from app.execution.execution_analysis_result import ExecutionAnalysisResult
from app.gui.action_approval_view import ActionApprovalView
from app.gui.budget_view import BudgetView
from app.gui.code_execution_view import CodeExecutionView
from app.gui.event_bridge import TkEventBridge
from app.gui.external_tool_view import ExternalToolView
from app.gui.input_view import AnalysisInputView
from app.gui.progress_view import AnalysisProgressView
from app.gui.result_view import AnalysisResultPanel
from app.judge.judge_result import JudgeResult
from app.presentation.action_approval_models import ActionApprovalRequest
from app.presentation.action_approval_presenter import ActionApprovalPresenter
from app.presentation.application_presenter import ApplicationPresenter
from app.presentation.code_execution_models import (
    CodeApprovalRequest,
    CodeExecutionRequest,
)
from app.presentation.code_execution_presenter import CodeExecutionPresenter
from app.presentation.event_buffer import (
    AnalysisEventBuffer,
    GuiEventSubscriber,
)
from app.presentation.input_models import AnalysisRequest
from app.presentation.input_presenter import AnalysisInputPresenter
from app.presentation.tool_budget_presenter import ToolBudgetPresenter
from app.presentation.view_models import (
    ApplicationState,
    ApplicationStatus,
)


class ProjectAegisApplicationShell:
    def __init__(
        self,
        root: tk.Misc,
        *,
        input_presenter: AnalysisInputPresenter,
        application_presenter: ApplicationPresenter,
        action_approval_presenter: ActionApprovalPresenter,
        code_execution_presenter: CodeExecutionPresenter,
        event_buffer: AnalysisEventBuffer,
        on_analysis_requested: Callable[[AnalysisRequest], None] | None = None,
        on_action_decision: Callable[[ActionApprovalRequest], None] | None = None,
        on_code_decision: Callable[[CodeApprovalRequest], None] | None = None,
        on_code_execution_requested: Callable[[CodeExecutionRequest], None]
        | None = None,
        on_cancel_requested: Callable[[], None] | None = None,
        result_provider: Callable[[], JudgeResult | None] | None = None,
    ) -> None:
        self._application_presenter = application_presenter
        self._state = application_presenter.initial_state()
        self._analysis_active = False

        self.frame = tk.Frame(root)

        self.input_view = AnalysisInputView(
            self.frame,
            input_presenter,
            on_analysis_requested,
            on_cancel_requested,
        )

        self.progress_view = AnalysisProgressView(self.frame)
        self.result_panel = AnalysisResultPanel(self.frame)

        self.action_approval_view = ActionApprovalView(
            self.frame,
            action_approval_presenter,
            on_action_decision,
        )

        self.code_execution_view = CodeExecutionView(
            self.frame,
            code_execution_presenter,
            on_code_decision,
            on_code_execution_requested,
        )

        tool_budget_presenter = ToolBudgetPresenter()

        self.external_tool_view = ExternalToolView(
            self.frame,
            tool_budget_presenter,
        )

        self.budget_view = BudgetView(
            self.frame,
            tool_budget_presenter,
        )

        for view in (
            self.input_view,
            self.progress_view,
            self.result_panel,
            self.action_approval_view,
            self.code_execution_view,
            self.external_tool_view,
            self.budget_view,
        ):
            view.frame.pack(fill="both", expand=True)

        self._event_subscriber = GuiEventSubscriber(event_buffer)

        self._event_bridge = TkEventBridge(
            root,
            event_buffer,
            application_presenter,
            self._state,
            self._on_event_state_changed,
        )

        set_result_provider = getattr(
            self._event_bridge,
            "set_result_provider",
            None,
        )

        if callable(set_result_provider):
            set_result_provider(result_provider)

        self.render(self._state)

    @property
    def state(self) -> ApplicationState:
        return self._state

    @property
    def event_subscriber(self) -> GuiEventSubscriber:
        return self._event_subscriber

    @property
    def analysis_active(self) -> bool:
        return self._analysis_active

    def render(self, state: ApplicationState) -> None:
        self._state = state
        self._event_bridge.set_state(state)

        self.progress_view.render(state.progress)
        self.result_panel.render(state)
        self.action_approval_view.render(state.iteration)
        self.external_tool_view.render(state)
        self.budget_view.render(state)

    def render_generated_code(
        self,
        generated_code: GeneratedCodeResult | None,
    ) -> None:
        self.code_execution_view.render_candidates(generated_code)

    def render_execution_results(
        self,
        results: tuple[ExecutionAnalysisResult, ...],
    ) -> None:
        self.code_execution_view.render_execution_results(results)

    def start_event_bridge(self) -> None:
        self._event_bridge.start()

    def stop_event_bridge(self) -> None:
        self._event_bridge.stop()

    def set_analysis_active(self, active: bool) -> None:
        if not isinstance(active, bool):
            raise TypeError("activeはboolで指定してください。")

        self._analysis_active = active
        self.input_view.set_enabled(not active)

    def clear(self) -> None:
        if self._analysis_active:
            raise RuntimeError("解析中は画面をクリアできません。")

        self.input_view.clear()
        self.progress_view.clear_history()
        self.code_execution_view.clear()

        self._state = self._application_presenter.initial_state()
        self.render(self._state)

    def _on_event_state_changed(
        self,
        state: ApplicationState,
    ) -> None:
        self.render(state)
        self.progress_view.append_history(state.progress)

        if state.progress.status in {
            ApplicationStatus.IDLE,
            ApplicationStatus.COMPLETED,
            ApplicationStatus.FAILED,
        }:
            self.set_analysis_active(False)