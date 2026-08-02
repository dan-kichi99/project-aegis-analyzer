from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from app.challenge.challenge_input import ChallengeInput

MAX_TOOL_REQUEST_METADATA_KEYS = 50


@dataclass(slots=True, frozen=True)
class ToolRequest:
    challenge: ChallengeInput
    working_directory: Path | None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = dict(self.metadata)
        if len(metadata) > MAX_TOOL_REQUEST_METADATA_KEYS:
            raise ValueError("metadataは最大50件です。")
        object.__setattr__(self, "metadata", MappingProxyType(metadata))
