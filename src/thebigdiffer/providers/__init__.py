"""Model-provider interfaces and implementations."""

from thebigdiffer.providers.base import ClaudeProvider
from thebigdiffer.providers.bedrock import BedrockClaudeProvider

__all__ = ["BedrockClaudeProvider", "ClaudeProvider"]
