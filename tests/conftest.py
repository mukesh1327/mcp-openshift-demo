"""Shared pytest fixtures and helpers.

Everything here runs against `FakeCluster` (tests/fakes.py) instead of a real
cluster, so the suite needs no kubeconfig and no network.
"""

from __future__ import annotations

import logging

import pytest
from mcp.server.mcpserver import MCPServer

from openshift_mcp.config import Config
from openshift_mcp.k8s import ClusterManager
from openshift_mcp.toolsets import Deps, register_all

from .fakes import FakeCluster


@pytest.fixture
def fake_cluster() -> FakeCluster:
    # A fresh recorder per test - inspect .calls, seed .raise_on / .objects.
    return FakeCluster()


@pytest.fixture
def manager(fake_cluster: FakeCluster) -> ClusterManager:
    # Two contexts: "default" is OpenShift, "staging" is plain Kubernetes -
    # enough to exercise context routing and the OpenShift gate.
    return ClusterManager.from_clients(
        {"default": fake_cluster, "staging": FakeCluster("staging", openshift=False)},
        "default",
    )


def build(manager: ClusterManager, cfg: Config) -> MCPServer:
    """Build a real MCPServer with the toolsets registered per `cfg`."""
    server = MCPServer(name="test", version="0")
    register_all(server, Deps(manager=manager, cfg=cfg, log=logging.getLogger("test")))
    return server


@pytest.fixture
def make_server(manager: ClusterManager):
    # Returns a factory so a test can pass its own Config (read_only, toolsets, ...).
    def _make(cfg: Config | None = None) -> MCPServer:
        return build(manager, cfg or Config())

    return _make


async def tool_names(server: MCPServer) -> set[str]:
    """The set of tool names a client would see - used to assert the tool surface."""
    return {t.name for t in await server.list_tools()}


async def call_text(server: MCPServer, name: str, args: dict) -> str:
    """Invoke a tool and return its text result (all our tools return one text block)."""
    result = await server.call_tool(name, args)
    return result.content[0].text
