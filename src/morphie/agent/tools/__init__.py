"""
Tool registry.

`get_default_tools()` is the single place that assembles the tools
Morphie's agent has available. Adding a new tool later means writing one
new module in this package and adding it to this list - nothing else
(the router, the agent loop, app.py) needs to change.
"""

from .base import Tool
from .calculator import calculator_tool
from .time import time_tool
from .web_search import web_search_tool


def get_default_tools() -> list[Tool]:
    return [calculator_tool, time_tool, web_search_tool]


__all__ = ["Tool", "get_default_tools", "calculator_tool", "time_tool", "web_search_tool"]
