"""Provider-neutral interface for Claude conversations."""

from __future__ import annotations

from typing import Any, Protocol


class ClaudeProvider(Protocol):
    """Minimal native-tool conversation interface required by the investigator."""

    def converse(self, **request: Any) -> dict[str, Any]: ...
