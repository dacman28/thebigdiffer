from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thebigdiffer.context import ApplicationContext
from thebigdiffer.investigator import ClaudeInvestigator, InvestigationConfig


class _ScriptedProvider:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        response = self.responses[len(self.requests) - 1]
        if isinstance(response, Exception):
            raise response
        return response


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before.joinpath("sample.py").write_text("TOKEN = 'old'\n", encoding="utf-8")
    after.joinpath("sample.py").write_text("TOKEN = 'new'\n", encoding="utf-8")
    return before, after


def _context() -> ApplicationContext:
    return ApplicationContext(
        repository_type="Python package",
        application_context="This repository implements a Python package.",
        deployment_context="Unknown.",
    )


def test_primary_loop_executes_native_source_tool_and_returns_report(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    provider = _ScriptedProvider(
        [
            {
                "stopReason": "tool_use",
                "usage": {"inputTokens": 100, "outputTokens": 20},
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "read_source",
                                    "input": {
                                        "version": "before",
                                        "path": "sample.py",
                                        "start_line": 1,
                                        "end_line": 1,
                                    },
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "usage": {"inputTokens": 150, "outputTokens": 30},
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "The patch changes TOKEN; security is unresolved."}],
                    }
                },
            },
        ]
    )

    result = ClaudeInvestigator(
        before_root=before,
        after_root=after,
        output_dir=tmp_path / "output",
        application_context=_context(),
        provider=provider,
    ).investigate()

    assert result.stop_reason == "model_end_turn"
    assert result.text == "The patch changes TOKEN; security is unresolved."
    assert result.usage.model_invocations == 2
    assert result.usage.tool_requests == result.usage.tool_executions == 1
    assert result.usage.retrieved_source_bytes == len(b"TOKEN = 'old'\n")
    assert [event["type"] for event in result.transcript.events] == [
        "model_request",
        "model_response",
        "tool_exchange",
        "model_request",
        "model_response",
    ]
    tool_result = provider.requests[1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["toolUseId"] == "tool-1"
    assert tool_result["content"][0]["json"]["source"] == "TOKEN = 'old'\n"
    assert provider.requests[0]["system"] == [{"text": result.prompt["text"]}]
    assert provider.requests[0]["toolConfig"] == result.tool_config
    assert (
        "<application_context supplied='true'"
        in provider.requests[0]["messages"][0]["content"][0]["text"]
    )
    assert (
        "<exact_patch path='sample.py'" in provider.requests[0]["messages"][0]["content"][0]["text"]
    )
    output = tmp_path / "output"
    assert (
        output.joinpath("primary-prompt.txt").read_text(encoding="utf-8") == result.prompt["text"]
    )
    assert output.joinpath("research-report.md").read_text(encoding="utf-8") == result.text + "\n"
    transcript = json.loads(output.joinpath("transcript.json").read_text(encoding="utf-8"))
    assert [event["sequence"] for event in transcript["events"]] == [1, 2, 3, 4, 5]
    assert transcript["final"]["stop_reason"] == "model_end_turn"
    assert transcript["identity"]["patch_sha256"] == result.patch.sha256
    assert transcript["source_preparation"]["mode"] == "directory"
    preparation = json.loads(output.joinpath("source-preparation.json").read_text(encoding="utf-8"))
    assert preparation == result.source_preparation
    assert preparation["mode"] == "directory"
    assert transcript["identity"]["source_preparation_sha256"] == preparation["manifest_sha256"]
    assert not list(output.glob("*.tmp"))


def test_primary_loop_records_provider_failure_without_retry(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    provider = _ScriptedProvider([RuntimeError("provider unavailable")])

    result = ClaudeInvestigator(
        before_root=before,
        after_root=after,
        output_dir=tmp_path / "output",
        application_context=_context(),
        provider=provider,
    ).investigate()

    assert len(provider.requests) == 1
    assert result.stop_reason == "model_transport_error_no_retry"
    assert "no security or benign classification is inferred" in result.text
    assert result.transcript.events[-1] == {
        "type": "model_transport_error",
        "stage": "primary",
        "stage_invocation": 1,
        "error_class": "RuntimeError",
        "error": "provider unavailable",
        "retry_attempted": False,
    }


def test_final_model_invocation_is_reserved_for_qualified_conclusion(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    provider = _ScriptedProvider(
        [
            {
                "stopReason": "tool_use",
                "usage": {},
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "toolUse": {
                                    "toolUseId": "tool-1",
                                    "name": "search_source",
                                    "input": {"version": "before", "query": "TOKEN"},
                                }
                            }
                        ],
                    }
                },
            },
            {
                "stopReason": "end_turn",
                "usage": {},
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": "Qualified final report."}],
                    }
                },
            },
        ]
    )
    config = InvestigationConfig(max_model_invocations=2)

    result = ClaudeInvestigator(
        before_root=before,
        after_root=after,
        output_dir=tmp_path / "output",
        application_context=_context(),
        provider=provider,
        config=config,
    ).investigate()

    notice = provider.requests[1]["messages"][-1]["content"][-1]["text"]
    assert "only the final stage model invocation remains" in notice
    assert result.stop_reason == "model_end_turn"


def test_investigator_refuses_to_overwrite_existing_artifacts(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    provider = _ScriptedProvider([])

    with pytest.raises(FileExistsError):
        ClaudeInvestigator(
            before_root=before,
            after_root=after,
            output_dir=output,
            application_context=_context(),
            provider=provider,
        ).investigate()

    assert provider.requests == []
