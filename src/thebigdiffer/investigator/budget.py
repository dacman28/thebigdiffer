"""Investigation budget and usage interfaces."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InvestigationBudget:
    """Fixed operational ceilings for one investigation."""

    max_model_invocations: int
    max_tool_requests: int
    max_retrieved_source_bytes: int
    spending_ceiling_usd: Decimal


@dataclass(frozen=True)
class InvestigationUsage:
    """Accumulated model, tool, source, token, and cost usage."""

    model_invocations: int = 0
    tool_requests: int = 0
    tool_executions: int = 0
    retrieved_source_bytes: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    estimated_cost_usd: Decimal = Decimal("0")
