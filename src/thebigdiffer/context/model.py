"""Application-context value types."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_CONTEXT_FIELD_CHARS = 4_000


@dataclass(frozen=True)
class ApplicationContext:
    """Factual context explicitly supplied for an investigation."""

    repository_type: str
    application_context: str
    deployment_context: str
    provenance: str = "explicitly supplied by the user"

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"application context field {name} must be non-empty text")
            if len(value) > MAX_CONTEXT_FIELD_CHARS:
                raise ValueError(
                    f"application context field {name} exceeds {MAX_CONTEXT_FIELD_CHARS} characters"
                )

    def serializable(self) -> dict[str, str]:
        """Return the exact persisted representation."""
        return asdict(self)

    def exact_text(self) -> str:
        """Render the validated model-visible factual context."""
        return (
            f"Repository type:\n{self.repository_type.strip()}\n\n"
            f"Application context:\n{self.application_context.strip()}\n\n"
            f"Deployment context:\n{self.deployment_context.strip()}\n"
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.exact_text().encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path) -> ApplicationContext:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("application context file must contain an object")
        expected = {
            "repository_type",
            "application_context",
            "deployment_context",
            "provenance",
        }
        if set(value) != expected:
            raise ValueError(
                "application context must contain exactly: " + ", ".join(sorted(expected))
            )
        return cls(**value)
