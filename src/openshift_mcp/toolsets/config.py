"""config toolset: inspect the clusters/contexts the server can talk to."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from . import Deps, serialize

_RO = ToolAnnotations(read_only_hint=True)


def register(server: Any, deps: Deps) -> None:
    cfg = deps.cfg
    mgr = deps.manager

    def contexts_list(
        probe: Annotated[
            bool,
            Field(
                description="also check each context's reachability and OpenShift status "
                "(slower; contacts every cluster)"
            ),
        ] = False,
    ) -> str:
        """List the cluster contexts this server can target. Every other tool
        takes an optional ``context`` argument naming one of these; omitting it
        uses the default context."""
        return serialize([asdict(info) for info in mgr.describe(probe=probe)], cfg.list_output)

    def configuration_view() -> str:
        """Show the effective server configuration (safety mode, toolsets,
        limits, default context)."""
        return serialize(
            {
                "default_context": mgr.default_context,
                "contexts": mgr.contexts(),
                "read_only": cfg.read_only,
                "disable_destructive": cfg.disable_destructive,
                "toolsets": list(cfg.toolsets),
                "list_limit": cfg.list_limit,
                "log_max_lines": cfg.log_max_lines,
                "request_timeout": cfg.request_timeout,
            },
            cfg.list_output,
        )

    server.add_tool(
        contexts_list,
        name="contexts_list",
        description="Read-only. List targetable cluster contexts and their status.",
        annotations=_RO,
    )
    server.add_tool(
        configuration_view,
        name="configuration_view",
        description="Read-only. Show the effective server configuration.",
        annotations=_RO,
    )
