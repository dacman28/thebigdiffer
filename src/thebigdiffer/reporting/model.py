"""Public reporting value types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from thebigdiffer.investigator.budget import InvestigationUsage
    from thebigdiffer.patch.model import PatchPresentation


@dataclass(frozen=True)
class Transcript:
    """Complete ordered record of model and tool events."""

    events: tuple[dict[str, Any], ...]
    conversation: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class InvestigationReport:
    """Qualified primary investigation result."""

    text: str
    stop_reason: str
    model_stop_reason: str | None
    transcript: Transcript
    usage: InvestigationUsage
    estimated_cost: dict[str, Any]
    prompt: dict[str, str]
    application_context: dict[str, Any]
    patch: PatchPresentation
    tool_config: dict[str, Any]
    source_inventory: dict[str, Any]
    source_preparation: dict[str, Any]
    configuration: dict[str, Any]
