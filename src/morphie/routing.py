"""
Greeting detection.

A bare "hi" doesn't need a model call: Morphie answers it locally, which
also means it works before any provider is configured. Everything else goes
to the agent, which decides for itself - through the model's structured tool
calls, never keyword matching - whether to use the calculator, the clock,
web search, or the user's documents.
"""

from __future__ import annotations

import re

_GREETING = re.compile(r"(?:hi+|hello+|hey+|yo+|hiya|howdy)[\s!.,]*", re.IGNORECASE)


def is_greeting(text: str) -> bool:
    return bool(_GREETING.fullmatch(text.strip())) if isinstance(text, str) else False
