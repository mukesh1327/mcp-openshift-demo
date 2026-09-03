"""Build the MCPServer, wire toolsets, and run a transport."""

from __future__ import annotations

import logging
import socket
import sys
from typing import Any

import anyio

from . import __version__
from .config import Config
from .k8s import ClusterManager
from .toolsets import Deps, register_all

_INSTRUCTIONS = (
    "Tools for observing and operating OpenShift/Kubernetes clusters. Use "
    "`resources_list` / `resources_get` for any kind (pass kind + apiVersion), "
    "`pods_log` for container logs, `events_list` for recent events. "
    "`contexts_list` lists the configured cluster contexts by name only; it does "
    "not check connectivity unless you pass `probe=true`, so a context appearing "
    "there does not mean its cluster is reachable. Every tool takes an optional "
    "`context` argument."
)

STREAMABLE_HTTP_PATH = "/mcp"


def configure_logging(cfg: Config) -> logging.Logger:
    """Set up root logging at ``cfg.log_level`` and return the package logger.

    stdio transport uses stdout for the JSON-RPC stream, so ALL logging must go
    to stderr - a stray line on stdout would corrupt the protocol.
    """
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger("openshift_mcp")


def build_server(cfg: Config, manager: ClusterManager, *, log: logging.Logger) -> Any:
    """Create the MCPServer and attach every tool that ``cfg`` permits.

    Returns the server, untyped (``Any``) because the MCP package is imported
    lazily here so ``--help`` / config errors don't pay the MCP import cost.
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="openshift-mcp-server",
        version=__version__,
        instructions=_INSTRUCTIONS,  # shown to the model so it knows which tool to reach for
    )
    # register_all inspects cfg (toolsets, read_only, disable_destructive) and
    # only attaches the tools that configuration permits.
    register_all(server, Deps(manager=manager, cfg=cfg, log=log))
    return server


def _add_health_routes(server: Any, manager: ClusterManager, log: logging.Logger) -> None:
    """Attach /healthz and /readyz to the HTTP transport (used by the k8s probes)."""
    from starlette.responses import PlainTextResponse

    # Liveness: the process is up and serving. Never touches the cluster.
    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Any) -> Any:
        return PlainTextResponse("ok")

    # Readiness: can we actually reach the default cluster's API right now?
    # The k8s client call is blocking, so run it off the event loop.
    @server.custom_route("/readyz", methods=["GET"])
    async def readyz(_request: Any) -> Any:
        try:
            await anyio.to_thread.run_sync(lambda: manager.get().server_version())
        except Exception as exc:
            log.warning("readiness check failed: %s", exc)
            return PlainTextResponse(f"not ready: {exc}", status_code=503)
        return PlainTextResponse("ok")


def run(cfg: Config) -> None:
    """Wire everything together and block serving the chosen transport."""
    log = configure_logging(cfg)
    log.info(
        "starting openshift-mcp-server %s (transport=%s, read_only=%s, toolsets=%s)",
        __version__,
        cfg.transport,
        cfg.read_only,
        ",".join(cfg.toolsets),
    )

    # Bound every socket op (including the dynamic client's discovery calls,
    # which take no explicit _request_timeout) so an unreachable API server
    # can never hang a tool call indefinitely.
    socket.setdefaulttimeout(cfg.request_timeout)

    # Resolves credentials + enumerates contexts now, but does NOT open any
    # cluster connection - ClusterClients are built lazily on first tool call.
    manager = ClusterManager.from_config(cfg)
    if manager.unavailable_reason:
        log.warning(
            "no cluster access (%s) - starting anyway; run `oc login` (or set "
            "--kubeconfig / --in-cluster) and it is picked up automatically, no restart",
            manager.unavailable_reason,
        )
    else:
        log.info(
            "contexts: %s (default: %s)",
            ", ".join(manager.contexts()),
            manager.default_context,
        )

    # Construct the MCPServer and attach the permitted tools (still no I/O).
    server = build_server(cfg, manager, log=log)

    if cfg.transport == "stdio":
        # One client, this process's stdin/stdout. Blocks until the pipe closes.
        server.run(transport="stdio")
    else:
        # HTTP: the MCP endpoint at /mcp, plus /healthz + /readyz for k8s probes.
        _add_health_routes(server, manager, log)
        log.info(
            "http transport on %s:%s (MCP endpoint %s)", cfg.host, cfg.port, STREAMABLE_HTTP_PATH
        )
        server.run(
            transport="streamable-http",
            host=cfg.host,
            port=cfg.port,
            streamable_http_path=STREAMABLE_HTTP_PATH,
        )
