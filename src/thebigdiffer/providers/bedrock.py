"""Amazon Bedrock native Converse provider for Claude."""

from __future__ import annotations

from typing import Any

import boto3  # type: ignore[import-untyped]
from botocore.config import Config  # type: ignore[import-untyped]


class BedrockClaudeProvider:
    """Thin no-retry provider adapter; the investigator records provider errors."""

    def __init__(self, *, region_name: str, client: Any | None = None) -> None:
        self.region_name = region_name
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=region_name,
            config=Config(
                connect_timeout=10,
                read_timeout=600,
                retries={"total_max_attempts": 1, "mode": "standard"},
            ),
        )

    def converse(self, **request: Any) -> dict[str, Any]:
        response = self._client.converse(**request)
        if not isinstance(response, dict):
            raise TypeError("Bedrock Converse returned a non-object response")
        return response
