import threading
from collections.abc import Callable
from datetime import datetime, timezone

from app.application.analysis_worker import AnalysisWorker
from app.challenge.challenge_service import ChallengeService
from app.events.analysis_event import AnalysisEvent, AnalysisEventType
from app.events.event_publisher import EventPublisher
from app.gui.application_shell import ProjectAegisApplicationShell
from app.judge.judge_result import JudgeResult
from app.presentation.action_approval_models import ActionApprovalRequest
from app.presentation.code_execution_models import (
    CodeApprovalRequest,
    CodeExecutionRequest,
)
from app.presentation.input_models import AnalysisRequest


class ApplicationController:
    def __init__(
        self,
        challenge_service: ChallengeService,
        event_publisher: EventPublisher,
        *,
        on_action_decision: Callable[[ActionApprovalRequest], None] | None = None,
        on_code_decision: Callable[[CodeApprovalRequest], None] | None = None,
        on_code_execution_requested: Callable[[CodeExecutionRequest], None]
        | None = None,
    ) -> None:
        self._challenge_service = challenge_service
        self._event_publisher = event_publisher
        self._on_action_decision = on_action_decision
        self._on_code_decision = on_code_decision
        self._on_code_execution_requested = on_code_execution_requested
        self._shell: ProjectAegisApplicationShell | None = None
        self._analysis_active = False
        self._worker: AnalysisWorker | None = None
        self._lock = threading.Lock()
        self._last_result: JudgeResult | None = None

    @property
    def analysis_active(self) -> bool:
        with self._lock:
            return self._analysis_active

    @property
    def worker(self) -> AnalysisWorker | None:
        with self._lock:
            return self._worker

    @property
    def last_result(self) -> JudgeResult | None:
        with self._lock:
            return self._last_result

    def connect_shell(self, shell: ProjectAegisApplicationShell) -> None:
        if self._shell is shell:
            return
        if self._shell is not None:
            self._event_publisher.unsubscribe(self._shell.event_subscriber)
        self._shell = shell
        self._event_publisher.subscribe(shell.event_subscriber)

    def disconnect_shell(self) -> None:
        if self._shell is not None:
            self._event_publisher.unsubscribe(self._shell.event_subscriber)
            self._shell = None

    def handle_analysis_request(self, request: AnalysisRequest) -> AnalysisWorker:
        with self._lock:
            if self._analysis_active or (
                self._worker is not None and self._worker.is_alive()
            ):
                raise RuntimeError("解析はすでに実行中です。")
            worker = AnalysisWorker(
                self._challenge_service.solve,
                request.question,
                request.file_paths,
                self._worker_completed,
                solve_with_cancel=getattr(
                    self._challenge_service,
                    "solve_with_cancel",
                    None,
                ),
            )
            self._worker = worker
            self._analysis_active = True
            self._last_result = None
        self._set_shell_active(True)
        worker.start()
        return worker

    def cancel_analysis(self) -> bool:
        with self._lock:
            worker = self._worker
            if worker is None or not worker.is_alive():
                return False
            worker.cancel()
            return True

    def handle_action_decision(self, request: ActionApprovalRequest) -> None:
        if self._on_action_decision is not None:
            self._on_action_decision(request)

    def handle_code_decision(self, request: CodeApprovalRequest) -> None:
        if self._on_code_decision is not None:
            self._on_code_decision(request)

    def handle_code_execution_request(self, request: CodeExecutionRequest) -> None:
        if self._on_code_execution_requested is not None:
            self._on_code_execution_requested(request)

    def _set_shell_active(self, active: bool) -> None:
        if self._shell is not None:
            self._shell.set_analysis_active(active)

    def _worker_completed(self, worker: AnalysisWorker) -> None:
        with self._lock:
            if worker is not self._worker:
                return
            self._analysis_active = False
            if not worker.cancel_requested and worker.error is None:
                self._last_result = worker.result
        if worker.cancel_requested:
            self._publish_cancelled()
        elif worker.error is not None:
            self._publish_failure(worker.error)

    def _publish_failure(self, error: Exception) -> None:
        self._event_publisher.publish(
            AnalysisEvent(
                AnalysisEventType.ANALYSIS_FAILED,
                "解析中にエラーが発生しました。",
                "application_controller",
                datetime.now(timezone.utc),
                {"error_type": type(error).__name__},
            )
        )

    def _publish_cancelled(self) -> None:
        self._event_publisher.publish(
            AnalysisEvent(
                AnalysisEventType.ANALYSIS_CANCELLED,
                "解析をキャンセルしました。",
                "application_controller",
                datetime.now(timezone.utc),
                {},
            )
        )
