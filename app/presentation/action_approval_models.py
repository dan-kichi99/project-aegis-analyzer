from dataclasses import dataclass
from enum import Enum

from app.presentation.view_models import ActionViewModel

MAX_APPROVAL_ACTIONS = 100
MAX_APPROVAL_MESSAGE_CHARACTERS = 500
MAX_APPROVAL_ACTION_ID_CHARACTERS = 200


class ActionApprovalDecision(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"


@dataclass(slots=True, frozen=True)
class ActionApprovalRequest:
    action_id: str
    decision: ActionApprovalDecision

    def __post_init__(self) -> None:
        if not self.action_id.strip():
            raise ValueError("action_idは空にできません。")
        if len(self.action_id) > MAX_APPROVAL_ACTION_ID_CHARACTERS:
            raise ValueError("action_idは200文字以内で指定してください。")
        if not isinstance(self.decision, ActionApprovalDecision):
            raise TypeError("decisionが不正です。")


@dataclass(slots=True, frozen=True)
class ActionApprovalState:
    actions: tuple[ActionViewModel, ...]
    selected_index: int | None
    selected_action: ActionViewModel | None
    message: str
    can_approve: bool
    can_reject: bool
    can_defer: bool

    def __post_init__(self) -> None:
        if len(self.actions) > MAX_APPROVAL_ACTIONS:
            raise ValueError("actionsは最大100件です。")
        if len(self.message) > MAX_APPROVAL_MESSAGE_CHARACTERS:
            raise ValueError("messageは500文字以内で指定してください。")
        if isinstance(self.selected_index, bool):
            raise TypeError("selected_indexにboolは指定できません。")
        if self.selected_index is None:
            if self.selected_action is not None:
                raise ValueError("未選択時にselected_actionは指定できません。")
        elif not 0 <= self.selected_index < len(self.actions):
            raise ValueError("selected_indexが範囲外です。")
        elif self.selected_action != self.actions[self.selected_index]:
            raise ValueError("selected_indexとselected_actionが一致しません。")
        decision_enabled = self.selected_action is not None and (
            self.selected_action.status == "proposed"
        )
        if (self.can_approve, self.can_reject, self.can_defer) != (
            decision_enabled,
            decision_enabled,
            decision_enabled,
        ):
            raise ValueError("Actionの状態と判断可否が一致しません。")
