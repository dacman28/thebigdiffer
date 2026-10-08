"""Validated application-context presentation."""

from __future__ import annotations

from typing import Any

from thebigdiffer.context.model import ApplicationContext


def application_context_record(context: ApplicationContext) -> dict[str, Any]:
    """Return the transcript/provenance record for supplied context."""
    return {
        "supplied": True,
        "exact_text": context.exact_text(),
        "sha256": context.sha256,
        "fields": context.serializable(),
        "provenance": context.provenance,
        "deployment_context_established": (
            context.deployment_context.strip().lower() not in {"unknown", "unknown."}
        ),
    }


def render_application_context(context: ApplicationContext) -> str:
    """Render the frozen benchmark's model-visible context block."""
    return (
        "<application_context supplied='true' provenance="
        f"{context.provenance!r} sha256={context.sha256!r}>\n"
        "This is explicitly supplied factual context, not repository-source evidence. It does "
        "not establish installation, public exposure, attacker influence, authentication, "
        "authorization, routes, roles, or other deployment facts beyond its exact text.\n\n"
        f"{context.exact_text()}"
        "</application_context>"
    )
