from __future__ import annotations

import pytest

from openshift_mcp.k8s import ClusterManager, ContextInfo

from .fakes import FakeCluster


def test_from_clients_resolves_default_and_named() -> None:
    east, west = FakeCluster("east"), FakeCluster("west", openshift=False)
    mgr = ClusterManager.from_clients({"east": east, "west": west}, "east")

    assert mgr.default_context == "east"
    assert mgr.get() is east
    assert mgr.get("west") is west


def test_unknown_context_raises_keyerror_naming_configured() -> None:
    mgr = ClusterManager.from_clients({"east": FakeCluster()}, "east")
    with pytest.raises(KeyError) as ei:
        mgr.get("nope")
    assert "east" in str(ei.value)


def test_default_must_be_configured() -> None:
    with pytest.raises(ValueError):
        ClusterManager.from_clients({"east": FakeCluster()}, "west")


def test_describe_names_only_by_default() -> None:
    mgr = ClusterManager.from_clients({"east": FakeCluster("east")}, "east")
    infos = mgr.describe()
    assert infos == [ContextInfo("east", True)]
    assert infos[0].reachable is None  # not probed


def test_describe_probes_when_asked() -> None:
    mgr = ClusterManager.from_clients(
        {"east": FakeCluster("east"), "west": FakeCluster("west", openshift=False)}, "east"
    )
    infos = {i.name: i for i in mgr.describe(probe=True)}
    assert infos["east"] == ContextInfo("east", True, True, True)
    assert infos["west"].openshift is False
    assert infos["west"].default is False
