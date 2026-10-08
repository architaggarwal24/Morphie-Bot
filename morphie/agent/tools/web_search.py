"""
Web search tool.

A SearchProvider abstraction sits behind the tool so a real backend can be
swapped in without touching the tool interface or the agent:

  - StubSearchProvider: the safe default. Returns an explicit "not
    configured" message instead of hardcoding some free/unofficial
    scraping approach that would be unreliable in production.
  - TavilySearchProvider: a real implementation, used automatically once
    TAVILY_API_KEY is set in the environment.

The web_search tool is always registered (unlike an approach that hides
the tool entirely when unconfigured) so the agent can still reason about
"I don't have live search right now" rather than the tool silently not
existing.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import requests

from .base import Tool

logger = logging.getLogger(__name__)

TAVILY_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 10


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str) -> str:
        """Return a short, human-readable summary of search results."""


class StubSearchProvider(SearchProvider):
    """Safe default when no real search provider is configured."""

    def search(self, query: str) -> str:
        return (
            "Web search is not currently configured, so I can't look that up "
            "live. Set TAVILY_API_KEY in .env to enable real web search."
        )


class TavilySearchProvider(SearchProvider):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str) -> str:
        try:
            response = requests.post(
                TAVILY_URL,
                json={"query": query, "max_results": 3},
                headers={"Authorization": f"Bearer {self.api_key}"},  # a header, not the body/URL
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            results = response.json().get("results", [])
        except requests.RequestException as exc:
            # requests' messages can include URLs and connection details: log only the type.
            logger.warning("Web search request failed (%s).", type(exc).__name__)
            return "Web search couldn't be reached right now, so I can't look that up live."
        except ValueError:
            return "Web search failed: the search provider returned an unreadable response."

        if not results:
            return f"No web results found for '{query}'."

        lines = []
        for r in results[:3]:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            snippet = (r.get("content") or "")[:200]
            lines.append(f"- {title}: {snippet} ({url})")
        return "\n".join(lines)


def get_search_provider() -> SearchProvider:
    """Chooses a provider at call time (not import time) so tests and
    config changes don't need a process restart. The key comes from
    Config, like every other setting - this module never reads the
    environment itself."""
    from config import Config  # lazy: keeps the tool library importable without app config

    if Config.TAVILY_API_KEY:
        return TavilySearchProvider(Config.TAVILY_API_KEY)
    return StubSearchProvider()


def web_search(query: str) -> str:
    return get_search_provider().search(query)


web_search_tool = Tool(
    name="web_search",
    description=(
        "Search the web for current information - news, facts, or anything "
        "you're not confident about from memory alone."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."}
        },
        "required": ["query"],
    },
    handler=web_search,
)
