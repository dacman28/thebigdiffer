from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from thebigdiffer.context import (
    ApplicationContext,
    application_context_record,
    render_application_context,
)
from thebigdiffer.investigator import (
    ClaudeInvestigator,
    InvestigationConfig,
    SpendingBudget,
    load_default_pricing,
    load_primary_prompt,
)
from thebigdiffer.patch import build_patch_presentation, render_primary_input
from thebigdiffer.reporting import sha256_json
from thebigdiffer.source import TOOL_CONFIG, SourceRepository

FIXTURE = Path(__file__).parent / "fixtures" / "autonomous-investigator-v1"


def _json(name: str) -> Any:
    return json.loads(FIXTURE.joinpath(name).read_text(encoding="utf-8"))


def _context() -> ApplicationContext:
    return ApplicationContext(**_json("application-context.json"))


def _store() -> SourceRepository:
    config = InvestigationConfig()
    return SourceRepository(
        FIXTURE / "source" / "before",
        FIXTURE / "source" / "after",
        max_lines_per_response=config.max_lines_per_tool_response,
        max_retrieved_bytes=config.max_retrieved_source_bytes,
        search_max_matches=config.search_max_matches,
        search_context_lines=config.search_context_lines,
    )


class _ScriptedProvider:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = copy.deepcopy(responses)
        self.requests: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(copy.deepcopy(request))
        return copy.deepcopy(self.responses[len(self.requests) - 1])


def test_golden_fixture_identity_and_file_hashes() -> None:
    manifest = _json("manifest.json")
    assert manifest["schema_version"] == 1
    assert manifest["kind"] == "derivative_compatibility_contract"
    assert manifest["research_repository_final_source_commit"] == (
        "ef31421da220fdcc864efbc52657b3dff2e20f3b"
    )
    assert manifest["validated_research_architecture_commit"] == (
        "1bd47dd6243aaf58d294a76258236506405defa0"
    )
    assert manifest["production_git_input_milestone_commit"] == (
        "ef31421da220fdcc864efbc52657b3dff2e20f3b"
    )
    assert manifest["frozen_research_tree_object"] == (
        "3848f859d854ba529292848b6227b7f7eb4e1cb8"
    )
    assert manifest["primary_prompt_sha256"] == (
        "f2973b032a0a76e1aed537e2975cc861941f40a7a95bf88d5d0435da3dd347ab"
    )
    for relative, identity in manifest["files"].items():
        payload = FIXTURE.joinpath(relative).read_bytes()
        assert len(payload) == identity["bytes"]
        assert hashlib.sha256(payload).hexdigest() == identity["sha256"]


def test_prompt_context_patch_and_tool_contract_match_golden_fixture() -> None:
    prompt = load_primary_prompt()
    assert prompt.text.encode("utf-8") == FIXTURE.joinpath("primary-prompt.txt").read_bytes()
    assert prompt.sha256 == _json("manifest.json")["primary_prompt_sha256"]

    context = _context()
    assert render_application_context(context) == FIXTURE.joinpath(
        "rendered-context.txt"
    ).read_text(encoding="utf-8")
    assert application_context_record(context) == _json("application-context-record.json")

    patch = build_patch_presentation(_store(), InvestigationConfig().max_initial_evidence_bytes)
    expected = _json("expected-patch.json")
    assert patch.text.encode("utf-8") == FIXTURE.joinpath("patch.txt").read_bytes()
    assert patch.sha256 == expected["sha256"]
    assert list(patch.changed_paths) == expected["changed_paths"]
    assert json.loads(json.dumps(patch.patch_records)) == expected["patch_records"]
    assert json.loads(json.dumps(patch.omitted_records)) == expected["omitted_records"]
    assert render_primary_input(context, patch) == expected["primary_input"]

    assert TOOL_CONFIG == _json("tool-config.json")
    assert sha256_json(TOOL_CONFIG) == _json("manifest.json")["tool_definitions_sha256"]


def test_all_source_tool_results_match_golden_fixture() -> None:
    store = _store()
    for expected in _json("expected-tool-results.json"):
        assert store.execute(expected["name"], expected["arguments"]) == expected["result"]


def test_cost_admission_matches_golden_fixture() -> None:
    probe = _json("budget-probe.json")
    budget = SpendingBudget(load_default_pricing(), Decimal("2.00"))
    assert list(budget.max_tokens(probe["request"], 4096)) == probe["before_admission"]
    added = budget.add(probe["usage_added"], 1)
    assert added == probe["added_cost"]
    assert list(budget.max_tokens(probe["request"], 4096)) == probe["after_admission"]


def test_primary_runtime_matches_standalone_golden_contract(tmp_path: Path) -> None:
    provider = _ScriptedProvider(_json("scripted-provider-responses.json"))
    output = tmp_path / "output"
    report = ClaudeInvestigator(
        before_root=FIXTURE / "source" / "before",
        after_root=FIXTURE / "source" / "after",
        output_dir=output,
        application_context=_context(),
        provider=provider,
    ).investigate()

    expected_runtime = _json("expected-runtime.json")
    expected_transcript = _json("expected-transcript.json")
    assert provider.requests == _json("expected-model-requests.json")
    assert report.text + "\n" == FIXTURE.joinpath("expected-report.md").read_text(
        encoding="utf-8"
    )
    assert report.stop_reason == expected_runtime["stop_reason"]
    assert report.model_stop_reason == expected_runtime["model_stop_reason"]
    usage = asdict(report.usage)
    usage["estimated_cost_usd"] = str(report.usage.estimated_cost_usd)
    assert usage == expected_runtime["usage"]
    assert report.estimated_cost == expected_runtime["estimated_cost"]
    assert report.source_inventory == expected_runtime["source_inventory"]
    assert report.source_preparation == expected_runtime["source_preparation"]
    assert list(report.transcript.events) == expected_transcript["events"]
    assert list(report.transcript.conversation) == expected_transcript["conversation"]

    persisted = json.loads(output.joinpath("transcript.json").read_text(encoding="utf-8"))
    persisted_events = [
        {key: value for key, value in event.items() if key not in {"sequence", "recorded_at"}}
        for event in persisted["events"]
    ]
    assert persisted_events == expected_transcript["events"]
    assert persisted["conversation"] == expected_transcript["conversation"]
    assert persisted["final"]["stop_reason"] == expected_runtime["stop_reason"]
    assert persisted["report"]["text"] == report.text
