from app.presentation.action_approval_models import (
    ActionApprovalDecision,
    ActionApprovalRequest,
    ActionApprovalState,
)
from app.presentation.view_models import ActionViewModel


class ActionApprovalPresenter:
    def initial_state(self) -> ActionApprovalState:
        return ActionApprovalState(
            actions=(),
            selected_index=None,
            selected_action=None,
            message="承認待ちActionはありません。",
            can_approve=False,
            can_reject=False,
            can_defer=False,
        )

    def present_actions(
        self, actions: tuple[ActionViewModel, ...]
    ) -> ActionApprovalState:
        return ActionApprovalState(
            actions=actions,
            selected_index=None,
            selected_action=None,
            message=(
                "Actionを選択してください。"
                if actions
                else "承認待ちActionはありません。"
            ),
            can_approve=False,
            can_reject=False,
            can_defer=False,
        )

    def select_action(
        self, state: ActionApprovalState, index: int | None
    ) -> ActionApprovalState:
        if index is None:
            return self.present_actions(state.actions)
        if isinstance(index, bool) or not 0 <= index < len(state.actions):
            raise ValueError("indexが範囲外です。")
        selected = state.actions[index]
        enabled = selected.status == "proposed"
        message = (
            "承認、拒否、または保留を選択してください。"
            if enabled
            else "このActionは現在判断できません。"
        )
        return ActionApprovalState(
            actions=state.actions,
            selected_index=index,
            selected_action=selected,
            message=message,
            can_approve=enabled,
            can_reject=enabled,
            can_defer=enabled,
        )

    def build_request(
        self,
        state: ActionApprovalState,
        decision: ActionApprovalDecision,
    ) -> ActionApprovalRequest:
        if not isinstance(decision, ActionApprovalDecision):
            raise TypeError("decisionが不正です。")
        if state.selected_action is None:
            raise ValueError("Actionが選択されていません。")
        allowed = {
            ActionApprovalDecision.APPROVE: state.can_approve,
            ActionApprovalDecision.REJECT: state.can_reject,
            ActionApprovalDecision.DEFER: state.can_defer,
        }
        if not allowed[decision]:
            raise ValueError("このActionは現在判断できません。")
        return ActionApprovalRequest(state.selected_action.action_id, decision)
