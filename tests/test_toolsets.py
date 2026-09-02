from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from openshift_mcp.config import Config

from .conftest import build, call_text, tool_names
from .fakes import FakeCluster, api_exception


async def test_default_tool_surface(make_server) -> None:
    names = await tool_names(make_server())
    # core reads + config always present
    assert {"resources_list", "resources_get", "pods_log", "events_list"} <= names
    assert {"contexts_list", "configuration_view"} <= names
    # non-destructive writes present by default
    assert {"resources_apply", "resources_scale"} <= names
    # destructive NOT present by default
    assert "resources_delete" not in names
    # openshift toolset present (register_openshift=True)
    assert {"projects_list", "routes_list", "workloads_restart", "builds_trigger"} <= names


async def test_read_only_hides_writes(make_server) -> None:
    names = await tool_names(make_server(Config(read_only=True)))
    for w in (
        "resources_apply",
        "resources_scale",
        "resources_delete",
        "workloads_restart",
        "builds_trigger",
    ):
        assert w not in names
    assert "resources_list" in names


async def test_destructive_opt_in(make_server) -> None:
    names = await tool_names(make_server(Config(disable_destructive=False)))
    assert "resources_delete" in names


async def test_openshift_toolset_gated_by_flag(manager) -> None:
    names = await tool_names(build(manager, Config(toolsets=("core", "config"))))
    assert "routes_list" not in names
    assert "resources_list" in names


async def test_openshift_tool_rejects_non_openshift_context() -> None:
    from openshift_mcp.k8s import ClusterManager

    mgr = ClusterManager.from_clients(
        {"vanilla": FakeCluster("vanilla", openshift=False)}, "vanilla"
    )
    server = build(mgr, Config())
    with pytest.raises(ToolError) as ei:
        await server.call_tool("routes_list", {"namespace": "demo"})
    assert "not an OpenShift cluster" in str(ei.value)


async def test_toolsets_flag_disables_group(manager) -> None:

    names = await tool_names(build(manager, Config(toolsets=("core",))))
    assert "contexts_list" not in names
    assert "routes_list" not in names
    assert "resources_list" in names


async def test_resources_list_strips_managed_fields(make_server) -> None:
    text = await call_text(make_server(), "resources_list", {"kind": "Pod", "namespace": "demo"})
    payload = json.loads(text)
    assert payload["items"][0]["metadata"].get("managedFields") is None
    assert "last-applied-configuration" not in json.dumps(payload)


async def test_resources_scale_issues_merge_patch(fake_cluster: FakeCluster, make_server) -> None:
    await call_text(
        make_server(),
        "resources_scale",
        {"kind": "Deployment", "name": "web", "namespace": "demo", "replicas": 3},
    )
    op, args, _ = fake_cluster.calls[-1]
    assert op == "patch"
    assert args[4] == {"spec": {"replicas": 3}}


async def test_scale_rejects_negative_replicas(make_server) -> None:
    with pytest.raises(ToolError):
        await call_text(
            make_server(),
            "resources_scale",
            {"kind": "Deployment", "name": "web", "namespace": "demo", "replicas": -1},
        )


async def test_workloads_restart_patches_template_annotation(
    fake_cluster: FakeCluster, make_server
) -> None:
    await call_text(
        make_server(),
        "workloads_restart",
        {"name": "web", "namespace": "demo"},
    )
    op, args, _ = fake_cluster.calls[-1]
    assert op == "patch"
    ann = args[4]["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in ann


async def test_builds_trigger_hits_instantiate_subresource(
    fake_cluster: FakeCluster, make_server
) -> None:
    await call_text(make_server(), "builds_trigger", {"name": "app", "namespace": "demo"})
    op, args, _ = fake_cluster.calls[-1]
    assert op == "instantiate"
    assert args[:4] == ("build.openshift.io/v1", "BuildConfig", "instantiate", "app")


async def test_unknown_context_is_clean_tool_error(make_server) -> None:
    with pytest.raises(ToolError) as ei:
        await call_text(make_server(), "resources_list", {"kind": "Pod", "context": "mars"})
    assert "mars" in str(ei.value) and "default" in str(ei.value)


async def test_api_error_is_mapped(manager, fake_cluster: FakeCluster) -> None:

    fake_cluster.raise_on["list"] = api_exception(403, "forbidden")
    server = build(manager, Config())
    with pytest.raises(ToolError) as ei:
        await server.call_tool("resources_list", {"kind": "Pod", "namespace": "demo"})
    assert "forbidden" in str(ei.value)


async def test_context_argument_routes(manager) -> None:

    server = build(manager, Config())
    # staging cluster reports not-openshift; contexts_list --probe should show it
    text = await call_text(server, "contexts_list", {"probe": True})
    infos = {i["name"]: i for i in json.loads(text)}
    assert infos["staging"]["openshift"] is False
    assert infos["default"]["default"] is True

    # default (no probe) does no cluster I/O
    text = await call_text(server, "contexts_list", {})
    infos = {i["name"]: i for i in json.loads(text)}
    assert infos["default"]["reachable"] is None
