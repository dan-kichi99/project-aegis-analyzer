import tkinter as tk
from collections.abc import Callable

from app.presentation.action_approval_models import (
    ActionApprovalDecision,
    ActionApprovalRequest,
)
from app.presentation.action_approval_presenter import ActionApprovalPresenter
from app.presentation.view_models import ActionViewModel, IterationViewModel


class ActionApprovalView:
    def __init__(
        self,
        parent: tk.Misc,
        presenter: ActionApprovalPresenter,
        on_decision: Callable[[ActionApprovalRequest], None] | None = None,
    ) -> None:
        self.presenter = presenter
        self.on_decision = on_decision
        self.state = presenter.initial_state()
        self.frame = tk.Frame(parent)
        self.action_list = tk.Listbox(self.frame)
        self.action_list.pack(fill="both", expand=True)
        self.action_list.bind("<<ListboxSelect>>", self._on_select)
        self.action_id_label = tk.Label(self.frame, text="")
        self.action_type_label = tk.Label(self.frame, text="")
        self.status_label = tk.Label(self.frame, text="")
        self.priority_label = tk.Label(self.frame, text="")
        self.description_label = tk.Label(self.frame, text="")
        self.approval_required_label = tk.Label(self.frame, text="")
        self.message_label = tk.Label(self.frame, text=self.state.message)
        self.approve_button = tk.Button(
            self.frame,
            text="承認",
            command=lambda: self._decide(ActionApprovalDecision.APPROVE),
        )
        self.reject_button = tk.Button(
            self.frame,
            text="拒否",
            command=lambda: self._decide(ActionApprovalDecision.REJECT),
        )
        self.defer_button = tk.Button(
            self.frame,
            text="保留",
            command=lambda: self._decide(ActionApprovalDecision.DEFER),
        )
        for widget in (
            self.action_id_label,
            self.action_type_label,
            self.status_label,
            self.priority_label,
            self.description_label,
            self.approval_required_label,
            self.message_label,
            self.approve_button,
            self.reject_button,
            self.defer_button,
        ):
            widget.pack(fill="x")
        self._sync()

    def render(self, iteration: IterationViewModel | None) -> None:
        actions = iteration.pending_actions if iteration is not None else ()
        self.state = self.presenter.present_actions(actions)
        self._sync()

    def clear(self) -> None:
        self.state = self.presenter.initial_state()
        self._sync()

    def _on_select(self, _event=None) -> None:
        selection = self.action_list.curselection()
        index = int(selection[0]) if selection else None
        self.state = self.presenter.select_action(self.state, index)
        self._sync_details()

    def _decide(self, decision: ActionApprovalDecision) -> None:
        try:
            request = self.presenter.build_request(self.state, decision)
        except ValueError:
            return
        if self.on_decision is not None:
            self.on_decision(request)

    def _sync(self) -> None:
        self.action_list.delete(0, tk.END)
        for action in self.state.actions:
            self.action_list.insert(tk.END, self._list_text(action))
        self._sync_details()

    def _sync_details(self) -> None:
        action = self.state.selected_action
        self.action_id_label.configure(
            text=f"Action ID：{action.action_id}" if action else "Action ID：未選択"
        )
        self.action_type_label.configure(
            text=f"種別：{action.action_type}" if action else "種別：未選択"
        )
        self.status_label.configure(
            text=f"状態：{action.status}" if action else "状態：未選択"
        )
        self.priority_label.configure(
            text=f"priority：{action.priority}" if action else "priority：未選択"
        )
        self.description_label.configure(
            text=f"説明：{action.description}" if action else "説明：未選択"
        )
        required = (
            "必要" if action is not None and action.requires_user_approval else "不要"
        )
        self.approval_required_label.configure(text=f"ユーザー承認：{required}")
        self.message_label.configure(text=self.state.message)
        self.approve_button.configure(
            state=tk.NORMAL if self.state.can_approve else tk.DISABLED
        )
        self.reject_button.configure(
            state=tk.NORMAL if self.state.can_reject else tk.DISABLED
        )
        self.defer_button.configure(
            state=tk.NORMAL if self.state.can_defer else tk.DISABLED
        )

    @staticmethod
    def _list_text(action: ActionViewModel) -> str:
        return (
            f"[{action.priority}] {action.action_type} / "
            f"{action.status} / {action.description}"
        )
