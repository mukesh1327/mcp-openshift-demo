"""Turn raw Kubernetes/OpenShift client errors into clear, actionable messages.

MCPServer converts a `ToolError` raised by a tool handler into an MCP tool
error whose message reaches the model, so handlers only need to raise
`tool_error(...)` with a good message. Any *other* exception is treated as a
crash and its text is withheld from the client.
"""

from __future__ import annotations

import json
import socket

from kubernetes.client.exceptions import ApiException  # raised on any non-2xx cluster response
from mcp.server.mcpserver.exceptions import ToolError as _MCPToolError  # our public base class
from urllib3.exceptions import MaxRetryError  # connection refused / DNS / all retries exhausted
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError  # socket read/connect timeout


class ToolError(_MCPToolError):
    """A user-facing error message for a failed tool call."""


def _api_message(exc: ApiException) -> str:
    """Pull the human-readable reason out of a Kubernetes Status error body,
    falling back to the HTTP reason phrase."""
    body = getattr(exc, "body", None)  # the raw HTTP response body, if the client kept it
    if body:
        try:
            parsed = json.loads(body)  # k8s returns a Status object as JSON
            # Status.message is the field kubectl prints, e.g. "pods \"x\" not found"
            if isinstance(parsed, dict) and parsed.get("message"):
                return str(parsed["message"])
        except (ValueError, TypeError):
            pass  # body wasn't JSON - fall through to the reason phrase
    # exc.reason is the HTTP status text ("Not Found"); last-resort default below
    return (exc.reason or "").strip() or "unknown error"


def tool_error(action: str, exc: BaseException) -> ToolError:
    """Map any exception a tool handler caught to a user-facing ToolError.

    `action` is a short present-participle phrase ("listing Pod", "scaling web")
    that gets prefixed to the message. Only ToolError text reaches the model;
    every other exception type is treated by MCPServer as an internal crash.
    """
    if isinstance(exc, ToolError):
        return exc  # already shaped (e.g. a manifest-validation error) - don't re-wrap

    if isinstance(exc, KeyError):
        # ClusterManager.get raises KeyError for an unknown context / no credentials.
        # str(KeyError) adds quotes, so unwrap args[0] to keep the message clean.
        return ToolError(f"{action}: {exc.args[0] if exc.args else exc}")

    if isinstance(exc, ApiException):
        # An HTTP error from the cluster - translate the status code to advice
        # the model (or user) can act on rather than a bare number.
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
        if status == 409:  # optimistic-concurrency clash on resourceVersion
            return ToolError(f"{action}: conflict - the resource changed concurrently, retry")
        if status == 422:  # the API server rejected the object (schema / admission webhook)
            return ToolError(f"{action}: invalid request: {_api_message(exc)}")
        if status == 429:  # client exceeded the API priority-and-fairness budget
            return ToolError(f"{action}: the cluster API is rate-limiting requests, retry later")
        # 500/503/... - nothing specific to advise, surface the server's own message
        return ToolError(f"{action}: cluster API error {status}: {_api_message(exc)}")

    # Network-level failures (never got an HTTP response back).
    if isinstance(exc, (Urllib3TimeoutError, socket.timeout, TimeoutError)):
        return ToolError(f"{action}: timed out waiting for the cluster to respond")
    if isinstance(exc, MaxRetryError):
        return ToolError(f"{action}: could not reach the cluster API ({exc.reason})")

    # LookupError from ClusterClient (unknown kind), ValueError, etc.
    return ToolError(f"{action}: {exc}")
