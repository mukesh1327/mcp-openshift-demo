"""config toolset: inspect the clusters/contexts the server can talk to."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from . import Deps, serialize

_RO = ToolAnnotations(read_only_hint=True)


def register(server: Any, deps: Deps) -> None:
    """Register the config toolset (``contexts_list``, ``configuration_view``).

    Both tools are always read-only and never touch a cluster unless explicitly
    asked to (``contexts_list probe=true``), so ``--read-only`` does not gate them.
    """
    cfg = deps.cfg
    mgr = deps.manager

    def contexts_list(
        probe: Annotated[
            bool,
            Field(
                description="actually contact each cluster to fill in reachable / "
                "openshift / error (slower). Set this whenever the user asks "
                "whether a cluster is up, reachable, or available."
            ),
        ] = False,
    ) -> str:
        """List the cluster contexts this server can target, from kubeconfig.

        By default (``probe=false``) this does no cluster I/O: it returns the
        configured context names with ``reachable`` and ``openshift`` set to
        null, meaning *not checked* - NOT that the cluster works. Whenever the
        question is whether a cluster is reachable, up, or available, call this
        with ``probe=true`` so ``reachable`` / ``openshift`` / ``error`` carry
        real values.

        Every other tool takes an optional ``context`` argument naming one of
        these; omitting it uses the default context."""
        # describe() returns a list[ContextInfo]; asdict() turns each into a plain
        # dict so serialize() can JSON/YAML it. probe flows straight through.
        return serialize([asdict(info) for info in mgr.describe(probe=probe)], cfg.list_output)

    def configuration_view() -> str:
        """Show the effective server configuration (safety mode, toolsets,
        limits, default context)."""
        # Lets the model (and the user) see which safety gates are active without
        # reading the process args - e.g. "is this server read-only?".
        return serialize(
            {
                # which cluster a context-less tool call would hit
                "default_context": mgr.default_context,
                "contexts": mgr.contexts(),
                # "ok", or the reason cluster tools are currently failing
                "cluster_access": mgr.unavailable_reason or "ok",
                # the two safety gates, so the model knows what it may attempt
                "read_only": cfg.read_only,
                "disable_destructive": cfg.disable_destructive,
                "toolsets": list(cfg.toolsets),
                # the caps applied to list_* / pods_log / every request
                "list_limit": cfg.list_limit,
                "log_max_lines": cfg.log_max_lines,
                "request_timeout": cfg.request_timeout,
            },
            cfg.list_output,
        )

    server.add_tool(
        contexts_list,
        name="contexts_list",
        description="Read-only. List the configured cluster contexts by name. "
        "Reports reachability/OpenShift status only when probe=true.",
        annotations=_RO,
    )
    server.add_tool(
        configuration_view,
        name="configuration_view",
        description="Read-only. Show the effective server configuration.",
        annotations=_RO,
    )
