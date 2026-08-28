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
                f"({exc.response.reason_phrase}). Check SEMANTIC_LAYER_MCP_TOKEN.",
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


# ── Per-task session reuse ────────────────────────────────────────────────────
#
# The plain client above opens a fresh MCP session per tool call. Real MCP
# clients (Claude Desktop, IDE integrations) hold ONE session per conversation,
# and the server keys its per-conversation memory (repeat-search suppression,
# list_models caching, the skill breadcrumb) off that session — so the per-call
# client silently defeats all of it and is LESS realistic, not more neutral.
# TaskSessionMCPClient maps the harness onto the honest equivalent: one MCP
# session per BIRD task (one task = one conversation).
#
# Implementation is raw streamable-HTTP rather than the SDK's ClientSession:
# the SDK transport is an async context manager that cannot be held open across
# ADK tool invocations (anyio cancel scopes bind to the entering task), while
# the protocol itself only needs the Mcp-Session-Id header echoed back. An
# expired/unknown session (server restart, GC) gets one transparent re-init.

_task_sessions: dict[str, str] = {}

# One in-flight call per task session. The streamable-HTTP server loses
# responses when two POSTs run concurrently on one Mcp-Session-Id — caught
# live 2026-08-28: a parallel explore_columns pair whose handlers both
# finished in 20ms while NEITHER response ever reached the client, which
# waited out its full deadline (the 30-minute production freezes, pre-
# deadline). ADK issues parallel tool calls, so without this lock a shared
# session races that server bug; with it they queue for the milliseconds a
# discovery call takes.
_task_locks: dict[str, asyncio.Lock] = {}


def _task_lock(task_id: str) -> asyncio.Lock:
    lock = _task_locks.get(task_id)
    if lock is None:
        lock = _task_locks[task_id] = asyncio.Lock()
    return lock


class TaskSessionMCPClient:
    """One persistent MCP session per task id, over bare streamable HTTP."""

    def __init__(self, endpoint: MCPEndpoint) -> None:
        self._endpoint = endpoint

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._endpoint.bearer_token:
            h["Authorization"] = f"Bearer {self._endpoint.bearer_token}"
        if session_id:
            h["Mcp-Session-Id"] = session_id
        return h

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        """Last JSON object in an SSE body (or plain-JSON body)."""
        payload: dict[str, Any] = {}
        for line in text.splitlines():
            if line.startswith("data: "):
                try:
                    payload = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
        if not payload and text.strip():
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                pass
        return payload

    async def _initialize(self, http: httpx.AsyncClient) -> str:
        resp = await http.post(
            self._endpoint.url,
            headers=self._headers(),
            json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "bird-interact-adk", "version": "1.0"},
                },
            },
        )
        resp.raise_for_status()
        session_id = resp.headers.get("mcp-session-id", "")
        if not session_id:
            raise MCPClientError("MCP server returned no Mcp-Session-Id on initialize")
        await http.post(
            self._endpoint.url,
            headers=self._headers(session_id),
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        return session_id

    async def acall_tool(
        self, task_id: str, name: str, arguments: dict[str, Any] | None = None
    ) -> str:
        # Hard OVERALL deadline, independent of httpx's per-read timeout: a
        # streamable-HTTP response that keeps sending SSE keepalive pings never
        # trips a read timeout, and a tools/call whose result event never
        # arrives froze the whole agent for exactly the orchestrator's 1800s
        # (observed live 2026-08-27, ~1 task in 12). A timed-out call surfaces
        # as a normal tool error the agent can retry; the run keeps moving.
        try:
            async with _task_lock(task_id):
                return await asyncio.wait_for(
                    self._acall_tool_inner(task_id, name, arguments),
                    timeout=240.0,
                )
        except asyncio.TimeoutError:
            raise MCPClientError(
                f"MCP call {name} exceeded the 240s task-session deadline "
                "(response stream stalled); retry the call"
            )

    async def _acall_tool_inner(
        self, task_id: str, name: str, arguments: dict[str, Any] | None = None
    ) -> str:
        async with httpx.AsyncClient(timeout=self._endpoint.timeout_s) as http:
            session_id = _task_sessions.get(task_id)
            if not session_id:
                session_id = await self._initialize(http)
                _task_sessions[task_id] = session_id
            body = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
            resp = await http.post(
                self._endpoint.url, headers=self._headers(session_id), json=body
            )
            if resp.status_code in (400, 404):
                # Session expired/unknown (server restart, GC): one re-init.
                session_id = await self._initialize(http)
                _task_sessions[task_id] = session_id
                resp = await http.post(
                    self._endpoint.url, headers=self._headers(session_id), json=body
                )
            if resp.status_code in (401, 403):
                raise MCPClientError(
                    f"MCP server rejected the request with HTTP {resp.status_code}. "
                    "Check SEMANTIC_LAYER_MCP_TOKEN.",
                    status_code=resp.status_code,
                )
            resp.raise_for_status()
            payload = self._parse_sse(resp.text)
            result = payload.get("result") or {}
            if "error" in payload:
                raise MCPToolError(str(payload["error"]))
            parts = [
                c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
            ]
            text = "\n".join(p for p in parts if p)
            if result.get("isError"):
                raise MCPToolError(text or f"tool {name} reported an error")
            return text
