from __future__ import annotations

import hashlib
from pathlib import Path

from thebigdiffer.investigator.prompt import (
    PRIMARY_PROMPT_SHA256,
    PRIMARY_PROMPT_VERSION,
    load_primary_prompt,
)

GOLDEN_PROMPT = (
    Path(__file__).parent / "fixtures" / "autonomous-investigator-v1" / "primary-prompt.txt"
)


def test_production_primary_prompt_is_byte_identical_to_golden_contract() -> None:
    golden = GOLDEN_PROMPT.read_bytes()
    production = load_primary_prompt()

    assert production.version == PRIMARY_PROMPT_VERSION == "primary-v1"
    assert production.text.encode("utf-8") == golden
    assert production.sha256 == PRIMARY_PROMPT_SHA256
    assert hashlib.sha256(golden).hexdigest() == PRIMARY_PROMPT_SHA256
