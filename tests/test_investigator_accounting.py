from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from thebigdiffer.investigator import (
    CostTracker,
    InvestigationConfig,
    SpendingBudget,
    load_default_pricing,
)
from thebigdiffer.providers import BedrockClaudeProvider

GOLDEN_MANIFEST = (
    Path(__file__).parent / "fixtures" / "autonomous-investigator-v1" / "manifest.json"
)


def test_packaged_pricing_matches_golden_contract() -> None:
    pricing = load_default_pricing()
    golden = json.loads(GOLDEN_MANIFEST.read_text(encoding="utf-8"))["pricing"]

    assert pricing.serializable() == golden


def test_cost_tracking_preserves_validated_values() -> None:
    pricing = load_default_pricing()
    production = CostTracker(pricing)
    usages = [
        {
            "inputTokens": 1234,
            "outputTokens": 321,
            "cacheReadInputTokens": 100,
            "cacheWriteInputTokens": 75,
            "cacheDetails": [
                {"inputTokens": 25, "ttl": "5m"},
                {"inputTokens": 25, "ttl": "1h"},
            ],
        },
        {"inputTokens": 500, "outputTokens": 12},
    ]

    records = []
    for invocation, usage in enumerate(usages, 1):
        records.append(production.add(usage, invocation))
    assert [record["estimated_cost_usd"] for record in records] == ["0.016391", "0.003080"]
    summary = production.summary()
    assert summary["input_tokens"] == 1734
    assert summary["output_tokens"] == 333
    assert summary["cache_read_input_tokens"] == 100
    assert summary["cache_write_input_tokens"] == 75
    assert summary["estimated_cost_usd"] == "0.019471"
    assert summary["calls"] == records

    request = {
        "modelId": pricing.model_id,
        "messages": [{"role": "user", "content": [{"text": "source" * 100}]}],
    }
    assert production.estimate_request_cost(request, 4096) == Decimal("0.1139325")


def test_spending_budget_preserves_validated_admission_math() -> None:
    budget = SpendingBudget(load_default_pricing(), Decimal("0.001"))
    request = {
        "modelId": "us.anthropic.claude-opus-4-6-v1",
        "messages": [{"role": "user", "content": [{"text": "x" * 1000}]}],
    }

    max_tokens, constrained = budget.max_tokens(request, 4096)

    assert constrained is True
    assert max_tokens is None or 512 <= max_tokens <= 4096


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"max_model_invocations": 0}, "greater than zero"),
        ({"search_context_lines": -1}, "must not be negative"),
        ({"spending_ceiling_usd": Decimal("0")}, "greater than zero"),
        ({"temperature": 0.1}, "temperature 0"),
        ({"model_id": "another-model"}, "locked"),
    ],
)
def test_investigation_config_rejects_behavior_drift(
    override: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        InvestigationConfig(**override)


class _FakeClient:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    def converse(self, **request: Any) -> dict[str, Any]:
        self.request = request
        return {"stopReason": "end_turn", "output": {"message": {"role": "assistant"}}}


def test_bedrock_provider_is_a_thin_native_converse_adapter() -> None:
    client = _FakeClient()
    provider = BedrockClaudeProvider(region_name="us-east-1", client=client)

    response = provider.converse(modelId="model", messages=[])

    assert client.request == {"modelId": "model", "messages": []}
    assert response["stopReason"] == "end_turn"
