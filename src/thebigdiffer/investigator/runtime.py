"""Validated autonomous primary-investigation loop."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from thebigdiffer.context import ApplicationContext, application_context_record
from thebigdiffer.investigator.accounting import (
    Pricing,
    SpendingBudget,
    load_default_pricing,
    money,
)
from thebigdiffer.investigator.budget import InvestigationUsage
from thebigdiffer.investigator.config import InvestigationConfig
from thebigdiffer.investigator.prompt import load_primary_prompt
from thebigdiffer.investigator.tool_contract import validate_bedrock_tool_config
from thebigdiffer.patch import build_patch_presentation, render_primary_input
from thebigdiffer.providers import ClaudeProvider
from thebigdiffer.reporting import (
    InvestigationArtifactWriter,
    InvestigationReport,
    Transcript,
    jsonable,
    now,
    sha256_json,
)
from thebigdiffer.repository import SourcePreparation
from thebigdiffer.source import TOOL_CONFIG, SourceRepository

PRIMARY_STAGE = "primary"


class ClaudeInvestigator:
    """Investigate an exact source patch using Claude and safe raw-source tools."""

    def __init__(
        self,
        *,
        before_root: Path,
        after_root: Path,
        output_dir: Path,
        application_context: ApplicationContext,
        provider: ClaudeProvider,
        config: InvestigationConfig | None = None,
        pricing: Pricing | None = None,
        source_preparation: SourcePreparation | None = None,
    ) -> None:
        self.before_root = before_root
        self.after_root = after_root
        self.output_dir = output_dir
        self.application_context = application_context
        self._provider = provider
        self.config = config or InvestigationConfig()
        self.pricing = pricing or load_default_pricing()
        self.source_preparation = source_preparation or SourcePreparation.directory()
        if self.pricing.model_id != self.config.model_id:
            raise ValueError("pricing model and investigation model must match")

    @property
    def provider(self) -> ClaudeProvider:
        return self._provider

    def investigate(self) -> InvestigationReport:
        prompt = load_primary_prompt()
        store = SourceRepository(
            self.before_root,
            self.after_root,
            max_lines_per_response=self.config.max_lines_per_tool_response,
            max_retrieved_bytes=self.config.max_retrieved_source_bytes,
            search_max_matches=self.config.search_max_matches,
            search_context_lines=self.config.search_context_lines,
        )
        patch = build_patch_presentation(store, self.config.max_initial_evidence_bytes)
        tool_config = copy.deepcopy(TOOL_CONFIG)
        validate_bedrock_tool_config(tool_config)
        initial_user_text = render_primary_input(self.application_context, patch)
        context_record = application_context_record(self.application_context)
        source_inventory = store.inventory_record()
        preparation_record = self.source_preparation.serializable()
        manifest = {
            "model_id": self.config.model_id,
            "prompt_version": prompt.version,
            "prompt_sha256": prompt.sha256,
            "application_context_sha256": self.application_context.sha256,
            "before_inventory_root_sha256": source_inventory["before"]["root_hash"],
            "after_inventory_root_sha256": source_inventory["after"]["root_hash"],
            "patch_sha256": patch.sha256,
            "tool_config_sha256": sha256_json(tool_config),
            "configuration": self.config.serializable(),
            "configuration_sha256": sha256_json(self.config.serializable()),
            "pricing": self.pricing.serializable(),
            "pricing_sha256": sha256_json(self.pricing.serializable()),
            "source_preparation_mode": preparation_record["mode"],
            "source_preparation_sha256": preparation_record["manifest_sha256"],
            "local_spending_ceiling_is_not_aws_billing_limit": True,
        }
        writer = InvestigationArtifactWriter(
            self.output_dir,
            {
                "schema_version": 1,
                "kind": "autonomous_patch_investigation_transcript",
                "started_at": now(),
                "identity": manifest,
                "prompt": {"version": prompt.version, "text": prompt.text, "sha256": prompt.sha256},
                "application_context": context_record,
                "patch": {
                    "text": patch.text,
                    "sha256": patch.sha256,
                    "changed_paths": patch.changed_paths,
                    "patch_records": patch.patch_records,
                    "omitted_records": patch.omitted_records,
                },
                "tool_config": tool_config,
                "deterministic_source_inventory": source_inventory,
                "source_preparation": preparation_record,
                "separation": {
                    "deterministic": (
                        "source preparation, application context, prompt identity, patch, "
                        "source inventory, tool definitions, and requested tool results"
                    ),
                    "model_generated": "model responses and research-report.md",
                },
            },
        )
        writer.write_inputs(
            prompt_text=prompt.text,
            application_context=context_record,
            patch_text=patch.text,
            tool_config=tool_config,
            source_inventory=source_inventory,
            source_preparation=preparation_record,
            manifest=manifest,
        )
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"text": initial_user_text}]}
        ]
        events: list[dict[str, Any]] = []

        def record(event: dict[str, Any]) -> None:
            events.append(event)
            writer.append(event)

        budget = SpendingBudget(self.pricing, self.config.spending_ceiling_usd)
        model_invocations = 0
        tool_requests = 0
        tool_executions = 0
        final_notice_added = False
        final_text = ""
        stop_reason = "unknown"
        model_stop_reason: str | None = None

        while model_invocations < self.config.max_model_invocations:
            reasons = _budget_reasons(store, self.config, model_invocations, tool_requests)
            if reasons and not final_notice_added:
                _add_budget_notice(messages, reasons)
                final_notice_added = True
                record(
                    {
                        "type": "operational_budget_notice",
                        "stage": PRIMARY_STAGE,
                        "reasons": reasons,
                    }
                )

            provisional: dict[str, Any] = {
                "modelId": self.config.model_id,
                "system": [{"text": prompt.text}],
                "messages": copy.deepcopy(messages),
                "inferenceConfig": {
                    "maxTokens": self.config.max_model_output_tokens,
                    "temperature": self.config.temperature,
                },
                "toolConfig": copy.deepcopy(tool_config),
            }
            max_tokens, constrained = budget.max_tokens(
                provisional, self.config.max_model_output_tokens
            )
            if constrained and not final_notice_added:
                reasons = ["combined estimated spending ceiling constrains the next response"]
                _add_budget_notice(messages, reasons)
                final_notice_added = True
                record(
                    {
                        "type": "operational_budget_notice",
                        "stage": PRIMARY_STAGE,
                        "reasons": reasons,
                    }
                )
                provisional["messages"] = copy.deepcopy(messages)
                max_tokens, _ = budget.max_tokens(provisional, self.config.max_model_output_tokens)
            if max_tokens is None:
                stop_reason = "combined_spending_ceiling_prevented_request"
                record(
                    {
                        "type": "model_request_not_issued",
                        "stage": PRIMARY_STAGE,
                        "reason": stop_reason,
                        "combined_estimated_cost_so_far_usd": money(budget.tracker.total),
                        "combined_spending_ceiling_usd": str(budget.ceiling),
                    }
                )
                break

            request = {
                **provisional,
                "messages": copy.deepcopy(messages),
                "inferenceConfig": {
                    "maxTokens": max_tokens,
                    "temperature": self.config.temperature,
                },
            }
            model_invocations += 1
            record(
                {
                    "type": "model_request",
                    "stage": PRIMARY_STAGE,
                    "stage_invocation": model_invocations,
                    "request_sha256": sha256_json(request),
                    "request": request,
                    "estimated_pre_call_cost_usd": money(
                        budget.tracker.estimate_request_cost(request, max_tokens)
                    ),
                }
            )
            try:
                response = self.provider.converse(**request)
            except Exception as error:
                stop_reason = "model_transport_error_no_retry"
                record(
                    {
                        "type": "model_transport_error",
                        "stage": PRIMARY_STAGE,
                        "stage_invocation": model_invocations,
                        "error_class": error.__class__.__name__,
                        "error": str(error),
                        "retry_attempted": False,
                    }
                )
                break

            output = response.get("output", {})
            output_message = output.get("message") if isinstance(output, dict) else None
            if not isinstance(output_message, dict):
                stop_reason = "malformed_provider_response_no_retry"
                record(
                    {
                        "type": "malformed_provider_response",
                        "stage": PRIMARY_STAGE,
                        "stage_invocation": model_invocations,
                        "response": jsonable(response),
                        "retry_attempted": False,
                    }
                )
                break
            raw_stop = response.get("stopReason")
            model_stop_reason = raw_stop if isinstance(raw_stop, str) else None
            stage_cost = budget.add(response.get("usage"), model_invocations)
            cost = {
                "stage": stage_cost,
                "combined_global_invocation": model_invocations,
                "combined_cumulative_estimated_cost_usd": money(budget.tracker.total),
            }
            record(
                {
                    "type": "model_response",
                    "stage": PRIMARY_STAGE,
                    "stage_invocation": model_invocations,
                    "response": jsonable(response),
                    "response_message_sha256": sha256_json(output_message),
                    "stop_reason": model_stop_reason,
                    "cost": cost,
                }
            )
            messages.append(copy.deepcopy(output_message))
            response_text = _message_text(output_message)
            if model_stop_reason != "tool_use":
                final_text = response_text
                stop_reason = (
                    "model_end_turn"
                    if model_stop_reason == "end_turn"
                    else f"model_{model_stop_reason}"
                )
                break

            tool_uses = _tool_uses(output_message)
            if not tool_uses:
                final_text = response_text
                stop_reason = "tool_use_stop_without_tool_request_no_retry"
                break
            if final_notice_added:
                final_text = response_text
                stop_reason = "budget_exhausted_model_requested_more_tools"
                record(
                    {
                        "type": "unexecuted_tool_requests",
                        "stage": PRIMARY_STAGE,
                        "reason": stop_reason,
                        "requests": tool_uses,
                    }
                )
                break

            result_blocks: list[dict[str, Any]] = []
            for tool_use in tool_uses:
                tool_requests += 1
                tool_use_id = tool_use.get("toolUseId")
                name = tool_use.get("name")
                arguments = tool_use.get("input")
                if tool_requests > self.config.max_tool_requests:
                    result = {
                        "ok": False,
                        "tool": name,
                        "error": "maximum source-tool request budget exhausted",
                    }
                elif not isinstance(tool_use_id, str) or not isinstance(name, str):
                    result = {
                        "ok": False,
                        "tool": str(name),
                        "error": "malformed native tool-use block",
                    }
                else:
                    tool_executions += 1
                    result = store.execute(name, arguments)
                record(
                    {
                        "type": "tool_exchange",
                        "stage": PRIMARY_STAGE,
                        "stage_tool_request_number": tool_requests,
                        "request": jsonable(tool_use),
                        "result": result,
                        "result_sha256": sha256_json(result),
                    }
                )
                result_block: dict[str, Any] = {
                    "toolUseId": (
                        tool_use_id if isinstance(tool_use_id, str) else "invalid-tool-id"
                    ),
                    "content": [{"json": result}],
                }
                if not result.get("ok"):
                    result_block["status"] = "error"
                result_blocks.append({"toolResult": result_block})
            messages.append({"role": "user", "content": result_blocks})
        else:
            stop_reason = "maximum_model_invocations_exhausted"

        if not final_text:
            final_text = (
                "Primary incomplete. The model did not produce a final response before stop "
                f"reason: {stop_reason}. Preserve the unresolved questions; no security or "
                "benign classification is inferred from exhaustion."
            )
        usage = InvestigationUsage(
            model_invocations=model_invocations,
            tool_requests=tool_requests,
            tool_executions=tool_executions,
            retrieved_source_bytes=store.retrieved_bytes,
            input_tokens=budget.tracker.input_tokens,
            output_tokens=budget.tracker.output_tokens,
            cache_read_input_tokens=budget.tracker.cache_read_tokens,
            cache_write_input_tokens=budget.tracker.cache_write_tokens,
            estimated_cost_usd=budget.tracker.total,
        )
        report = InvestigationReport(
            text=final_text,
            stop_reason=stop_reason,
            model_stop_reason=model_stop_reason,
            transcript=Transcript(tuple(events), tuple(copy.deepcopy(messages))),
            usage=usage,
            estimated_cost=budget.tracker.summary(),
            prompt={"version": prompt.version, "text": prompt.text, "sha256": prompt.sha256},
            application_context=context_record,
            patch=patch,
            tool_config=tool_config,
            source_inventory=source_inventory,
            source_preparation=preparation_record,
            configuration=self.config.serializable(),
        )
        writer.complete(report)
        return report


def _budget_reasons(
    store: SourceRepository,
    config: InvestigationConfig,
    invocations: int,
    tool_requests: int,
) -> list[str]:
    reasons: list[str] = []
    if tool_requests >= config.max_tool_requests:
        reasons.append("stage source-tool request limit exhausted")
    if store.retrieved_bytes >= config.max_retrieved_source_bytes:
        reasons.append("stage retrieved-source byte limit exhausted")
    if invocations >= config.max_model_invocations - 1:
        reasons.append("only the final stage model invocation remains")
    return reasons


def _budget_notice(reasons: list[str]) -> str:
    return (
        "Operational budget notice: "
        + "; ".join(reasons)
        + ". Do not request more tools. Provide a qualified stage conclusion from source "
        "actually inspected. Preserve missing evidence and unresolved questions explicitly."
    )


def _add_budget_notice(messages: list[dict[str, Any]], reasons: list[str]) -> None:
    text = _budget_notice(reasons)
    if (
        messages
        and messages[-1].get("role") == "user"
        and any("toolResult" in block for block in messages[-1].get("content", []))
    ):
        messages[-1]["content"].append({"text": text})
    else:
        messages.append({"role": "user", "content": [{"text": text}]})


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    return "\n".join(
        block["text"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ).strip()


def _tool_uses(message: dict[str, Any]) -> list[dict[str, Any]]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [
        block["toolUse"]
        for block in content
        if isinstance(block, dict) and isinstance(block.get("toolUse"), dict)
    ]
