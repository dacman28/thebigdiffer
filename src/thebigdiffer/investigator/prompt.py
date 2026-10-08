"""Loading and identity for the frozen production prompt."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib.resources import files

PRIMARY_PROMPT_VERSION = "primary-v1"
PRIMARY_PROMPT_SHA256 = "f2973b032a0a76e1aed537e2975cc861941f40a7a95bf88d5d0435da3dd347ab"


@dataclass(frozen=True)
class PromptIdentity:
    """Versioned prompt bytes and their reproducible identity."""

    version: str
    text: str
    sha256: str


def load_primary_prompt() -> PromptIdentity:
    """Load the validated primary prompt and reject packaging drift."""
    text = (
        files("thebigdiffer.investigator.prompts")
        .joinpath("primary-v1.txt")
        .read_text(encoding="utf-8")
    )
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != PRIMARY_PROMPT_SHA256:
        raise RuntimeError(
            "production primary prompt hash mismatch: "
            f"expected {PRIMARY_PROMPT_SHA256}, got {digest}"
        )
    return PromptIdentity(PRIMARY_PROMPT_VERSION, text, digest)
