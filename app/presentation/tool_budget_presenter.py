from app.presentation.view_models import (
    ApplicationState,
    BudgetViewModel,
    ExternalToolViewModel,
)


class ToolBudgetPresenter:
    def present_external_tools(
        self, state: ApplicationState | None
    ) -> tuple[ExternalToolViewModel, ...]:
        return state.external_tools if state is not None else ()

    def present_budget(
        self, state: ApplicationState | None
    ) -> BudgetViewModel | None:
        return state.budget if state is not None else None
