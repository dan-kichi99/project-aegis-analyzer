from pathlib import Path

from app.external_tools.process_request import (
    MAX_PROCESS_ARGUMENT_CHARACTERS,
    MAX_PROCESS_ARGUMENTS,
    ExternalProcessRequest,
)
from app.external_tools.tool import ExternalToolType
from app.external_tools.tool_policy import (
    AllowedTool,
    ExternalToolInvocation,
    ToolArgumentKind,
    ToolArgumentRule,
    ToolPolicyDecision,
    ToolPolicyDenialReason,
    ToolPolicyEvaluation,
)
from app.external_tools.tool_registry import ExternalToolRegistry


class ExternalToolRequestBuilder:
    def __init__(self, registry: ExternalToolRegistry) -> None:
        self.registry = registry

    def build(self, invocation: ExternalToolInvocation) -> ToolPolicyEvaluation:
        reasons: list[ToolPolicyDenialReason] = []
        if invocation.tool_type is ExternalToolType.CUSTOM:
            reasons.append(ToolPolicyDenialReason.CUSTOM_TOOL_NOT_ALLOWED)
        tool = self.registry.get(invocation.tool_type)
        if tool is None:
            reasons.append(ToolPolicyDenialReason.TOOL_NOT_REGISTERED)
        elif not self._valid_executable(tool.executable):
            reasons.append(ToolPolicyDenialReason.EXECUTABLE_INVALID)

        working_valid = self._valid_working_directory(invocation.working_directory)
        if not working_valid:
            reasons.append(ToolPolicyDenialReason.WORKING_DIRECTORY_INVALID)
        elif not self._within(
            invocation.working_directory.resolve(), self.registry.allowed_working_root
        ):
            reasons.append(ToolPolicyDenialReason.WORKING_DIRECTORY_OUTSIDE_ROOT)

        maximum = tool.max_arguments if tool is not None else MAX_PROCESS_ARGUMENTS
        if len(invocation.arguments) > maximum:
            reasons.append(ToolPolicyDenialReason.TOO_MANY_ARGUMENTS)
        if any(
            len(argument) > MAX_PROCESS_ARGUMENT_CHARACTERS
            for argument in invocation.arguments
        ):
            reasons.append(ToolPolicyDenialReason.ARGUMENT_TOO_LONG)
        if any(
            not isinstance(argument, str) or "\0" in argument
            for argument in invocation.arguments
        ):
            reasons.append(ToolPolicyDenialReason.INVALID_ARGUMENT)
        if tool is not None and working_valid and any(
            not self._argument_allowed(argument, tool, invocation.working_directory)
            for argument in invocation.arguments
            if isinstance(argument, str) and "\0" not in argument
        ):
            reasons.append(ToolPolicyDenialReason.ARGUMENT_NOT_ALLOWED)

        if reasons:
            return ToolPolicyEvaluation(
                ToolPolicyDecision.DENY,
                False,
                reasons[0],
                tuple(reasons),
                "外部Tool実行要求はPolicyにより拒否されました。",
                None,
            )
        process_request = ExternalProcessRequest(
            executable=tool.executable,
            arguments=invocation.arguments,
            working_directory=invocation.working_directory,
            timeout_seconds=tool.timeout_seconds,
            max_stdout_bytes=tool.max_stdout_bytes,
            max_stderr_bytes=tool.max_stderr_bytes,
        )
        return ToolPolicyEvaluation(
            ToolPolicyDecision.ALLOW,
            True,
            None,
            (),
            "外部Tool実行要求はPolicyで許可されました。",
            process_request,
        )

    def _valid_executable(self, executable: Path) -> bool:
        return (
            executable.is_absolute()
            and not executable.is_symlink()
            and executable.exists()
            and executable.is_file()
        )

    def _valid_working_directory(self, directory: Path) -> bool:
        return (
            directory.is_absolute()
            and not directory.is_symlink()
            and directory.exists()
            and directory.is_dir()
        )

    def _argument_allowed(
        self,
        argument: str,
        tool: AllowedTool,
        working_directory: Path,
    ) -> bool:
        if argument in tool.allowed_exact_arguments:
            return True
        if any(argument.startswith(prefix) for prefix in tool.allowed_argument_prefixes):
            return True
        return any(
            self._matches_rule(argument, rule, working_directory)
            for rule in tool.argument_rules
        )

    def _matches_rule(
        self,
        argument: str,
        rule: ToolArgumentRule,
        working_directory: Path,
    ) -> bool:
        if rule.kind is ToolArgumentKind.EXACT:
            return argument == rule.value
        if rule.kind is ToolArgumentKind.PREFIX:
            return argument.startswith(rule.value)
        path = Path(argument)
        if not path.is_absolute() or path.is_symlink():
            return False
        if not path.exists() or not path.is_file():
            return False
        resolved = path.resolve()
        return self._within(resolved, working_directory.resolve()) and self._within(
            resolved, self.registry.allowed_working_root
        )

    def _within(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True
