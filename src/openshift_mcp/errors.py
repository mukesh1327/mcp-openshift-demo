"""Turn raw Kubernetes/OpenShift client errors into clear, actionable messages.

MCPServer converts a `ToolError` raised by a tool handler into an MCP tool
error whose message reaches the model, so handlers only need to raise
`tool_error(...)` with a good message. Any *other* exception is treated as a
crash and its text is withheld from the client.
"""

from __future__ import annotations

import json
import socket

from kubernetes.client.exceptions import ApiException
from mcp.server.mcpserver.exceptions import ToolError as _MCPToolError
from urllib3.exceptions import MaxRetryError
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError


class ToolError(_MCPToolError):
    """A user-facing error message for a failed tool call."""


def _api_message(exc: ApiException) -> str:
    body = getattr(exc, "body", None)
    if body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict) and parsed.get("message"):
                return str(parsed["message"])
        except (ValueError, TypeError):
            pass
    return (exc.reason or "").strip() or "unknown error"


def tool_error(action: str, exc: BaseException) -> ToolError:
    """Build a ToolError describing a failed cluster operation."""
    if isinstance(exc, ToolError):
        return exc
    if isinstance(exc, KeyError):
        # ClusterManager.get raises KeyError for an unknown context name.
        return ToolError(f"{action}: {exc.args[0] if exc.args else exc}")

    if isinstance(exc, ApiException):
        status = exc.status
        if status == 404:
            return ToolError(f"{action}: not found")
        if status == 403:
            return ToolError(
                f"{action}: forbidden - the credentials lack RBAC permission for this "
                f"(check the Role/ClusterRole bound to the ServiceAccount or user)"
            )
        if status == 401:
            return ToolError(
                f"{action}: unauthorized - the cluster rejected the credentials "
                f"(the token may be expired; re-run `oc login`)"
            )
        if status == 409:
            return ToolError(f"{action}: conflict - the resource changed concurrently, retry")
        if status == 422:
            return ToolError(f"{action}: invalid request: {_api_message(exc)}")
        if status == 429:
            return ToolError(f"{action}: the cluster API is rate-limiting requests, retry later")
        return ToolError(f"{action}: cluster API error {status}: {_api_message(exc)}")

    if isinstance(exc, (Urllib3TimeoutError, socket.timeout, TimeoutError)):
        return ToolError(f"{action}: timed out waiting for the cluster to respond")
    if isinstance(exc, MaxRetryError):
        return ToolError(f"{action}: could not reach the cluster API ({exc.reason})")

    return ToolError(f"{action}: {exc}")
