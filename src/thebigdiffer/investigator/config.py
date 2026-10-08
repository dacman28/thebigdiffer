"""Validated autonomous-investigator configuration interface."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

MODEL_ID = "us.anthropic.claude-opus-4-6-v1"


@dataclass(frozen=True)
class InvestigationConfig:
    """Operational limits for one primary investigation."""

    model_id: str = MODEL_ID
    region_name: str = "us-east-1"
    max_model_invocations: int = 12
    max_tool_requests: int = 30
    max_lines_per_tool_response: int = 200
    max_retrieved_source_bytes: int = 128 * 1024
    max_initial_evidence_bytes: int = 256 * 1024
    max_model_output_tokens: int = 4096
    spending_ceiling_usd: Decimal = Decimal("2.00")
    temperature: float = 0.0
    search_max_matches: int = 20
    search_context_lines: int = 2

    def __post_init__(self) -> None:
        if self.model_id != MODEL_ID:
            raise ValueError(f"autonomous investigator is locked to {MODEL_ID}")
        integer_limits = (
            self.max_model_invocations,
            self.max_tool_requests,
            self.max_lines_per_tool_response,
            self.max_retrieved_source_bytes,
            self.max_initial_evidence_bytes,
            self.max_model_output_tokens,
            self.search_max_matches,
        )
        if min(integer_limits) <= 0:
            raise ValueError("all investigation limits must be greater than zero")
        if self.search_context_lines < 0:
            raise ValueError("search_context_lines must not be negative")
        if self.spending_ceiling_usd <= 0:
            raise ValueError("spending_ceiling_usd must be greater than zero")
        if self.temperature != 0.0:
            raise ValueError("the validated investigator uses temperature 0")

    def serializable(self) -> dict[str, Any]:
        value = asdict(self)
        value["spending_ceiling_usd"] = str(self.spending_ceiling_usd)
        return value
