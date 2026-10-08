"""Factual application context supplied to an investigation."""

from thebigdiffer.context.model import MAX_CONTEXT_FIELD_CHARS, ApplicationContext
from thebigdiffer.context.rendering import application_context_record, render_application_context

__all__ = [
    "MAX_CONTEXT_FIELD_CHARS",
    "ApplicationContext",
    "application_context_record",
    "render_application_context",
]
