from app.iteration.external_tool_iteration_result import ExternalToolIterationResult

MAX_FORMATTED_TOOL_RESULTS = 20
MAX_FORMATTED_TOOL_ITEM_CHARACTERS = 1_000
MAX_FORMATTED_TOOL_TOTAL_CHARACTERS = 10_000


class ExternalToolEvidenceFormatter:
    def format(
        self,
        results: tuple[ExternalToolIterationResult, ...],
    ) -> tuple[str, ...]:
        formatted: list[str] = []
        total = 0
        for result in results[:MAX_FORMATTED_TOOL_RESULTS]:
            parts = [
                f"tool={result.tool_type.value}",
                f"status={result.status.value}",
                f"summary={result.summary}",
            ]
            if result.tool_result.exit_code not in (None, 0):
                parts.append(f"exit_code={result.tool_result.exit_code}")
            parts.extend(
                f"evidence[{item.source}]={item.detail}"
                for item in result.tool_result.evidence
            )
            text = "\n".join(parts)[:MAX_FORMATTED_TOOL_ITEM_CHARACTERS]
            remaining = MAX_FORMATTED_TOOL_TOTAL_CHARACTERS - total
            if remaining <= 0:
                break
            text = text[:remaining]
            formatted.append(text)
            total += len(text)
        return tuple(formatted)
