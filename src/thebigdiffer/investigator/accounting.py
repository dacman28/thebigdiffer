"""Validated token, cost, and local spending-ceiling accounting."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

from thebigdiffer.investigator.budget import InvestigationUsage
from thebigdiffer.investigator.config import MODEL_ID


@dataclass(frozen=True)
class Pricing:
    """Versioned pricing provenance for local cost estimates."""

    model_id: str
    pricing_tier: str
    routing_scope: str
    currency: str
    unit: str
    input_tokens: Decimal
    output_tokens: Decimal
    cache_write_5m_tokens: Decimal
    cache_write_1h_tokens: Decimal
    cache_read_tokens: Decimal
    effective_date: str
    verified_on: str
    source: str
    source_location: str
    note: str

    @classmethod
    def load(cls, path: Path) -> Pricing:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("model_id") != MODEL_ID:
            raise ValueError(f"pricing must apply to required model {MODEL_ID}")
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_write_5m_tokens",
            "cache_write_1h_tokens",
            "cache_read_tokens",
        ):
            data[name] = Decimal(data[name])
            if data[name] < 0:
                raise ValueError(f"pricing field {name} must not be negative")
        return cls(**data)

    def serializable(self) -> dict[str, Any]:
        value = asdict(self)
        for key, item in tuple(value.items()):
            if isinstance(item, Decimal):
                value[key] = str(item)
        return value


def load_default_pricing() -> Pricing:
    """Load the pricing record frozen for the validated benchmark."""
    resource = files("thebigdiffer.investigator.pricing").joinpath(
        "opus-4.6-bedrock-2026-05-12.json"
    )
    with resource.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("packaged pricing must contain an object")
    for name in (
        "input_tokens",
        "output_tokens",
        "cache_write_5m_tokens",
        "cache_write_1h_tokens",
        "cache_read_tokens",
    ):
        data[name] = Decimal(data[name])
    pricing = Pricing(**data)
    if pricing.model_id != MODEL_ID:
        raise ValueError(f"pricing must apply to required model {MODEL_ID}")
    return pricing


class CostTracker:
    """Provider-reported usage and conservative pre-call cost estimates."""

    def __init__(self, pricing: Pricing) -> None:
        self.pricing = pricing
        self.total = Decimal("0")
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.calls: list[dict[str, Any]] = []

    def add(self, usage: object, invocation: int) -> dict[str, Any]:
        values = usage if isinstance(usage, dict) else {}
        input_tokens = _nonnegative_int(values.get("inputTokens"))
        output_tokens = _nonnegative_int(values.get("outputTokens"))
        cache_read = _nonnegative_int(values.get("cacheReadInputTokens"))
        cache_write = _nonnegative_int(values.get("cacheWriteInputTokens"))
        write_cost = Decimal("0")
        details = values.get("cacheDetails")
        detailed_tokens = 0
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                tokens = _nonnegative_int(detail.get("inputTokens"))
                detailed_tokens += tokens
                rate = (
                    self.pricing.cache_write_1h_tokens
                    if detail.get("ttl") == "1h"
                    else self.pricing.cache_write_5m_tokens
                )
                write_cost += _token_cost(tokens, rate)
        if cache_write > detailed_tokens:
            write_cost += _token_cost(
                cache_write - detailed_tokens, self.pricing.cache_write_1h_tokens
            )
        cost = (
            _token_cost(input_tokens, self.pricing.input_tokens)
            + _token_cost(output_tokens, self.pricing.output_tokens)
            + _token_cost(cache_read, self.pricing.cache_read_tokens)
            + write_cost
        )
        self.total += cost
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write
        record = {
            "invocation": invocation,
            "usage": _jsonable(values),
            "estimated_cost_usd": money(cost),
            "cumulative_estimated_cost_usd": money(self.total),
        }
        self.calls.append(record)
        return record

    def summary(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_tokens,
            "cache_write_input_tokens": self.cache_write_tokens,
            "estimated_cost_usd": money(self.total),
            "pricing": self.pricing.serializable(),
            "calls": self.calls,
        }

    def usage(self, *, model_invocations: int = 0) -> InvestigationUsage:
        return InvestigationUsage(
            model_invocations=model_invocations,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cache_read_input_tokens=self.cache_read_tokens,
            cache_write_input_tokens=self.cache_write_tokens,
            estimated_cost_usd=self.total,
        )

    def estimate_request_cost(self, request: dict[str, Any], max_output_tokens: int) -> Decimal:
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        estimated_input_tokens = math.ceil(len(encoded) / 3)
        return _token_cost(estimated_input_tokens, self.pricing.input_tokens) + _token_cost(
            max_output_tokens, self.pricing.output_tokens
        )


class SpendingBudget:
    """Local estimated ceiling; it is not an AWS billing limit."""

    def __init__(self, pricing: Pricing, ceiling: Decimal) -> None:
        self.pricing = pricing
        self.ceiling = ceiling
        self.tracker = CostTracker(pricing)

    def add(self, usage: object, invocation: int) -> dict[str, Any]:
        return self.tracker.add(usage, invocation)

    def max_tokens(self, request: dict[str, Any], configured: int) -> tuple[int | None, bool]:
        projected = self.tracker.total + self.tracker.estimate_request_cost(request, configured)
        if projected <= self.ceiling:
            return configured, False
        encoded = json.dumps(request, ensure_ascii=False, sort_keys=True).encode("utf-8")
        estimated_input_tokens = math.ceil(len(encoded) / 3)
        input_cost = _token_cost(estimated_input_tokens, self.pricing.input_tokens)
        remaining = self.ceiling - self.tracker.total - input_cost
        affordable = math.floor(
            max(Decimal("0"), remaining) * Decimal(1_000_000) / self.pricing.output_tokens
        )
        if affordable < 512:
            return None, True
        return min(configured, affordable), True


def money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _token_cost(tokens: int, rate: Decimal) -> Decimal:
    return Decimal(tokens) * rate / Decimal(1_000_000)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return repr(value)
