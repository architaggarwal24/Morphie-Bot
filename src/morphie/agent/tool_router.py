"""
Tool Router.

This is the only place tool arguments get validated and tool handlers get
executed. The Agent Orchestrator never touches a tool's Python code
directly - it only ever calls ToolRouter.execute() and gets back a
structured ToolResult, whether the call succeeded, failed validation, or
the handler raised.

Validation here is intentionally simple (required fields + basic type
checking against the tool's JSON schema) rather than a full JSON-schema
implementation - enough to catch malformed arguments from the model
before they ever reach a tool's handler.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .tools import Tool, get_default_tools

logger = logging.getLogger(__name__)

# Tool results go straight into the LLM's context (and back to the browser):
# bound both what a model may pass in and what a tool may hand back.
MAX_ARGUMENT_CHARS = 2000
MAX_TOOL_OUTPUT_CHARS = 6000

_JSON_TYPE_MAP: dict[str, Any] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


@dataclass
class ToolResult:
    tool_name: str
    arguments: dict[str, Any]
    output: str
    success: bool
    error: str | None = None


class ToolRouter:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = tools if tools is not None else get_default_tools()
        self._by_name = {t.name: t for t in self.tools}

    def get_schemas(self) -> list[dict] | None:
        """Structured tool definitions for the LLM provider's tool-calling
        API. Returns None (not an empty list) when there are no tools, so
        callers can pass it straight through without an extra check."""
        return [t.to_schema() for t in self.tools] or None

    def has_tool(self, name: str) -> bool:
        return name in self._by_name

    def _validate(self, tool: Tool, arguments: Any) -> str | None:
        """Returns a human-readable error if `arguments` don't satisfy the
        tool's schema, else None."""
        if not isinstance(arguments, dict):
            return "Arguments must be a JSON object."

        schema = tool.parameters or {}
        required = schema.get("required", [])
        properties = schema.get("properties", {})

        for field in required:
            if field not in arguments:
                return f"Missing required argument '{field}'."

        for key, value in arguments.items():
            prop = properties.get(key)
            if prop is None:
                continue  # unknown extra argument - ignore rather than hard-fail
            if isinstance(value, str) and len(value) > MAX_ARGUMENT_CHARS:
                return f"Argument '{key}' is too long (max {MAX_ARGUMENT_CHARS} characters)."
            expected = _JSON_TYPE_MAP.get(prop.get("type"))
            if expected and not isinstance(value, expected):
                return (
                    f"Argument '{key}' should be of type '{prop.get('type')}', "
                    f"got {type(value).__name__}."
                )
        return None

    def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._by_name.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name, arguments=arguments or {}, output="", success=False,
                error=f"Unknown tool '{name}'.",
            )

        arguments = arguments or {}
        validation_error = self._validate(tool, arguments)
        if validation_error:
            return ToolResult(
                tool_name=name, arguments=arguments, output="", success=False, error=validation_error
            )

        try:
            output = str(tool.handler(**arguments))
        except Exception as exc:  # noqa: BLE001 - a tool must never crash the agent loop
            # The exception text can hold paths, keys or user data, so it goes to
            # the operator's log (type only; details at DEBUG) and never to the
            # model, the user, or the browser.
            logger.warning("Tool '%s' raised %s.", name, type(exc).__name__)
            logger.debug("Tool '%s' failure details", name, exc_info=True)
            return ToolResult(
                tool_name=name, arguments=arguments, output="", success=False,
                error=f"The {name} tool ran into a problem and couldn't finish.",
            )
        if len(output) > MAX_TOOL_OUTPUT_CHARS:
            output = output[:MAX_TOOL_OUTPUT_CHARS] + "\n...[truncated]"
        return ToolResult(tool_name=name, arguments=arguments, output=output, success=True)
