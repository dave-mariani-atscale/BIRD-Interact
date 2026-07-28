"""Sync HTTP MCP client for calling a semantic-layer's MCP server (e.g. AtScale).

Adapted from mcp-eval's agent/mcp_client.py (already proven against the same
AtScale MCP endpoint) — trimmed to just the piece BIRD-Interact-ADK needs:
calling a named tool with a plain args dict, no model/OpenAI-tool-call plumbing.
Each call opens a fresh session, runs one request, and tears it down.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any

import httpx

if sys.version_info >= (3, 11):
    _BaseExceptionGroup = BaseExceptionGroup
else:
    from exceptiongroup import BaseExceptionGroup as _BaseExceptionGroup


class MCPClientError(RuntimeError):
    """Raised when an MCP request fails before reaching tool execution."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MCPToolError(RuntimeError):
    """Raised when the MCP server executes a tool and reports an error result."""


@dataclass(frozen=True)
class MCPEndpoint:
    """Connection target for an HTTP MCP server."""

    url: str
    bearer_token: str | None = None
    timeout_s: float = 120.0


class MCPClient:
    """Sync HTTP MCP client exposing `call_tool`."""

    def __init__(self, endpoint: MCPEndpoint) -> None:
        self._endpoint = endpoint

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Invoke a tool by name with a plain args dict. Returns the stringified result.

        Sync entry point — uses asyncio.run() internally, so this must NOT be
        called from code that's already running inside an event loop (e.g.
        ADK tool functions called from the agent's own async runtime — use
        `acall_tool` there instead). Safe from db_environment's grading path,
        which is dispatched via asyncio.to_thread (a plain thread, no loop).
        """
        return _run_with_clean_errors(self._call_tool_async(name, arguments or {}), self._endpoint.url)

    async def acall_tool(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Async entry point — await directly from code already inside an
        event loop (e.g. ADK tool functions). Same error translation as
        `call_tool`, without the asyncio.run() wrapper that would conflict
        with an already-running loop."""
        try:
            return await self._call_tool_async(name, arguments or {})
        except _BaseExceptionGroup as eg:
            leaf = _first_leaf(eg)
            if isinstance(leaf, (MCPClientError, MCPToolError)):
                raise leaf from eg
            raise _translate_mcp_error(leaf, self._endpoint.url) from eg
        except (MCPClientError, MCPToolError):
            raise
        except (httpx.HTTPStatusError, httpx.HTTPError) as e:
            raise _translate_mcp_error(e, self._endpoint.url) from e

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> str:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with (
            httpx.AsyncClient(headers=self._headers(), timeout=self._endpoint.timeout_s) as http_client,
            streamable_http_client(self._endpoint.url, http_client=http_client) as (read, write),
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                payload = _stringify_result_content(result.content)
                if result.is_error:
                    raise MCPToolError(payload or f"tool {name} reported an error")
                return payload

    def _headers(self) -> dict[str, str] | None:
        if self._endpoint.bearer_token:
            return {"Authorization": f"Bearer {self._endpoint.bearer_token}"}
        return None


def _run_with_clean_errors(coro: Any, url: str) -> Any:
    try:
        return asyncio.run(coro)
    except _BaseExceptionGroup as eg:
        leaf = _first_leaf(eg)
        if isinstance(leaf, (MCPClientError, MCPToolError)):
            raise leaf from eg
        raise _translate_mcp_error(leaf, url) from eg
    except (MCPClientError, MCPToolError):
        raise
    except (httpx.HTTPStatusError, httpx.HTTPError) as e:
        raise _translate_mcp_error(e, url) from e


def _first_leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, _BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _translate_mcp_error(exc: BaseException, url: str) -> MCPClientError:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return MCPClientError(
                f"MCP server at {url} rejected the request with HTTP {status} "
                f"({exc.response.reason_phrase}). Check ATSCALE_MCP_TOKEN.",
                status_code=status,
            )
        return MCPClientError(f"MCP server at {url} returned HTTP {status} ({exc.response.reason_phrase}).", status_code=status)
    if isinstance(exc, httpx.ConnectError):
        return MCPClientError(f"could not connect to MCP server at {url}: {exc}")
    if isinstance(exc, httpx.HTTPError):
        return MCPClientError(f"MCP transport error against {url}: {exc}")
    return MCPClientError(f"MCP request to {url} failed: {exc}")


def _stringify_result_content(content: list[Any]) -> str:
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
            continue
        try:
            parts.append(json.dumps(block.model_dump(mode="json"), default=str))
        except Exception:
            parts.append(str(block))
    return "\n".join(parts)
