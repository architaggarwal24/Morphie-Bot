"""
Base Tool definition.

A Tool bundles the common interface every tool implements: a name, a
description, a JSON-schema for its arguments, and the Python handler that
actually performs the action. Validating arguments and catching handler
errors is the ToolRouter's job (morphie/agent/tool_router.py) - that's
what turns "did this tool call succeed?" into a structured result instead
of every tool re-implementing its own error handling contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the tool's arguments
    handler: Callable[..., str]

    def to_schema(self) -> dict:
        """Shape expected by LLM provider tool-calling APIs (OpenAI-style,
        which Mistral, OpenAI and most others share)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
