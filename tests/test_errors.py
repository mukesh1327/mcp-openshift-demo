"""errors.tool_error: mapping API status codes and network failures to messages."""

from __future__ import annotations

from openshift_mcp.errors import ToolError, tool_error

from .fakes import api_exception


def test_maps_status_codes() -> None:
    assert "not found" in str(tool_error("getting pod", api_exception(404)))
    assert "forbidden" in str(tool_error("listing pods", api_exception(403)))
    assert "unauthorized" in str(tool_error("listing pods", api_exception(401)))
    assert "rate-limiting" in str(tool_error("listing pods", api_exception(429)))
    assert "conflict" in str(tool_error("scaling", api_exception(409)))


def test_includes_api_message_for_unmapped() -> None:
    msg = str(tool_error("applying x", api_exception(500, "etcd unavailable")))
    assert "500" in msg and "etcd unavailable" in msg


def test_timeout_and_passthrough() -> None:
    assert "timed out" in str(tool_error("listing pods", TimeoutError()))
    assert str(tool_error("x", ValueError("weird"))) == "x: weird"


def test_tool_error_is_passed_through() -> None:
    original = ToolError("already good")
    assert tool_error("x", original) is original
