"""Atomic persistence for auditable autonomous investigations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thebigdiffer.reporting.model import InvestigationReport
from thebigdiffer.reporting.serialization import jsonable, sha256_json, sha256_text


def now() -> str:
    return datetime.now(UTC).isoformat()


class InvestigationArtifactWriter:
    """Persist deterministic inputs and flush every runtime event atomically."""

    def __init__(self, output_dir: Path, initial: dict[str, Any]) -> None:
        self.output_dir = output_dir
        self.transcript_path = output_dir / "transcript.json"
        output_dir.mkdir(parents=True, exist_ok=False)
        self.data = initial
        self.data["events"] = []
        self._flush_transcript()

    def write_inputs(
        self,
        *,
        prompt_text: str,
        application_context: dict[str, Any],
        patch_text: str,
        tool_config: dict[str, Any],
        source_inventory: dict[str, Any],
        source_preparation: dict[str, Any],
        manifest: dict[str, Any],
    ) -> None:
        self._write_text("primary-prompt.txt", prompt_text)
        self._write_json("application-context.json", application_context)
        self._write_text("patch-presentation.txt", patch_text)
        self._write_json("tool-definitions.json", tool_config)
        self._write_json("source-inventory.json", source_inventory)
        self._write_json("source-preparation.json", source_preparation)
        self._write_json("investigation-manifest.json", manifest)

    def append(self, event: dict[str, Any]) -> None:
        sequence = len(self.data["events"]) + 1
        self.data["events"].append({"sequence": sequence, "recorded_at": now(), **event})
        self._flush_transcript()

    def complete(self, report: InvestigationReport) -> None:
        report_text = report.text.rstrip() + "\n"
        usage = {
            **asdict(report.usage),
            "estimated_cost_usd": str(report.usage.estimated_cost_usd),
        }
        metrics = {
            "stop_reason": report.stop_reason,
            "model_stop_reason": report.model_stop_reason,
            "usage": usage,
            "estimated_cost": report.estimated_cost,
            "prompt_version": report.prompt["version"],
            "prompt_sha256": report.prompt["sha256"],
            "application_context_sha256": report.application_context["sha256"],
            "patch_sha256": report.patch.sha256,
            "tool_config_sha256": sha256_json(report.tool_config),
            "before_inventory_root_sha256": report.source_inventory["before"]["root_hash"],
            "after_inventory_root_sha256": report.source_inventory["after"]["root_hash"],
            "source_preparation_mode": report.source_preparation["mode"],
            "source_preparation_sha256": report.source_preparation["manifest_sha256"],
            "report_sha256": sha256_text(report_text),
            "finished_at": now(),
            "local_spending_ceiling_is_not_aws_billing_limit": True,
        }
        self._write_text("research-report.md", report_text)
        self._write_json("metrics.json", metrics)
        self.data.update(
            {
                "conversation": report.transcript.conversation,
                "report": {"text": report.text, "sha256": sha256_text(report.text)},
                "final": metrics,
                "finished_at": metrics["finished_at"],
            }
        )
        self._flush_transcript()

    def _flush_transcript(self) -> None:
        self._write_json_path(self.transcript_path, self.data)

    def _write_json(self, name: str, value: object) -> None:
        self._write_json_path(self.output_dir / name, value)

    def _write_text(self, name: str, value: str) -> None:
        path = self.output_dir / name
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(value, encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _write_json_path(path: Path, value: object) -> None:
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(
            json.dumps(jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
