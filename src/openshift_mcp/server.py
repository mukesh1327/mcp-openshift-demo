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
    "`contexts_list` shows which clusters are reachable; every tool takes an "
    "optional `context` argument."
)

STREAMABLE_HTTP_PATH = "/mcp"


def configure_logging(cfg: Config) -> logging.Logger:
    # stdio transport uses stdout for the protocol stream, so logs go to stderr.
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return logging.getLogger("openshift_mcp")


def build_server(cfg: Config, manager: ClusterManager, *, log: logging.Logger) -> Any:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="openshift-mcp-server",
        version=__version__,
        instructions=_INSTRUCTIONS,
    )
    register_all(server, Deps(manager=manager, cfg=cfg, log=log))
    return server


def _add_health_routes(server: Any, manager: ClusterManager, log: logging.Logger) -> None:
    from starlette.responses import PlainTextResponse

    @server.custom_route("/healthz", methods=["GET"])
    async def healthz(_request: Any) -> Any:
        return PlainTextResponse("ok")

    @server.custom_route("/readyz", methods=["GET"])
    async def readyz(_request: Any) -> Any:
        try:
            await anyio.to_thread.run_sync(lambda: manager.get().server_version())
        except Exception as exc:
            log.warning("readiness check failed: %s", exc)
            return PlainTextResponse(f"not ready: {exc}", status_code=503)
        return PlainTextResponse("ok")


def run(cfg: Config) -> None:
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

    manager = ClusterManager.from_config(cfg)
    log.info("contexts: %s (default: %s)", ", ".join(manager.contexts()), manager.default_context)

    server = build_server(cfg, manager, log=log)

    if cfg.transport == "stdio":
        server.run(transport="stdio")
    else:
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
