import tkinter as tk
from tkinter import ttk

from app.presentation.view_models import ApplicationStatus, ProgressViewModel

MAX_PROGRESS_HISTORY = 100


class AnalysisProgressView:
    def __init__(self, parent: tk.Misc) -> None:
        self.frame = tk.Frame(parent)
        self.status_label = tk.Label(self.frame, text="")
        self.phase_label = tk.Label(self.frame, text="")
        self.message_label = tk.Label(self.frame, text="")
        self.agent_label = tk.Label(self.frame, text="")
        self.error_label = tk.Label(self.frame, text="")
        self.progressbar = ttk.Progressbar(self.frame, maximum=100)
        self.history_list = tk.Listbox(self.frame, height=10)
        for widget in (
            self.status_label,
            self.phase_label,
            self.message_label,
            self.agent_label,
            self.error_label,
            self.progressbar,
            self.history_list,
        ):
            widget.pack(fill="x")
        self._history: list[str] = []
        self._indeterminate_running = False

    @property
    def history(self) -> tuple[str, ...]:
        return tuple(self._history)

    def render(self, progress: ProgressViewModel) -> None:
        self.status_label.configure(text=progress.status.value)
        self.phase_label.configure(text=progress.phase)
        self.message_label.configure(text=progress.message)
        self.agent_label.configure(text=progress.current_agent or "")
        self.error_label.configure(text=progress.error_type or "")
        if progress.progress_percent is not None:
            self._stop_indeterminate()
            self.progressbar.configure(mode="determinate", value=progress.progress_percent)
        elif progress.status is ApplicationStatus.ANALYZING:
            self.progressbar.configure(mode="indeterminate")
            if not self._indeterminate_running:
                self.progressbar.start()
                self._indeterminate_running = True
        else:
            self._stop_indeterminate()
            value = 100 if progress.status is ApplicationStatus.COMPLETED else 0
            self.progressbar.configure(mode="determinate", value=value)

    def append_history(self, progress: ProgressViewModel) -> None:
        parts = [f"[{progress.phase}]", progress.message]
        if progress.current_agent:
            parts.append(f"Agent={progress.current_agent}")
        if progress.error_type:
            parts.append(f"Error={progress.error_type}")
        self._history.append(" ".join(parts)[:1_000])
        if len(self._history) > MAX_PROGRESS_HISTORY:
            del self._history[0]
        self._sync_history()

    def clear_history(self) -> None:
        self._history.clear()
        self._sync_history()

    def _stop_indeterminate(self) -> None:
        if self._indeterminate_running:
            self.progressbar.stop()
            self._indeterminate_running = False

    def _sync_history(self) -> None:
        self.history_list.delete(0, tk.END)
        for item in self._history:
            self.history_list.insert(tk.END, item)
