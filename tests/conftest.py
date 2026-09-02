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
    return FakeCluster()


@pytest.fixture
def manager(fake_cluster: FakeCluster) -> ClusterManager:
    return ClusterManager.from_clients(
        {"default": fake_cluster, "staging": FakeCluster("staging", openshift=False)},
        "default",
    )


def build(manager: ClusterManager, cfg: Config) -> MCPServer:
    server = MCPServer(name="test", version="0")
    register_all(server, Deps(manager=manager, cfg=cfg, log=logging.getLogger("test")))
    return server


@pytest.fixture
def make_server(manager: ClusterManager):
    def _make(cfg: Config | None = None) -> MCPServer:
        return build(manager, cfg or Config())

    return _make


async def tool_names(server: MCPServer) -> set[str]:
    return {t.name for t in await server.list_tools()}


async def call_text(server: MCPServer, name: str, args: dict) -> str:
    result = await server.call_tool(name, args)
    return result.content[0].text
