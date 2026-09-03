"""ClusterManager: context resolution, lazy caching, and describe()/probe()."""

from __future__ import annotations

import pytest

from openshift_mcp.config import Config
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


def test_missing_kubeconfig_is_not_fatal(tmp_path) -> None:
    cfg = Config(kubeconfig=str(tmp_path / "does-not-exist.yaml"))
    mgr = ClusterManager.from_config(cfg)

    assert mgr.unavailable_reason is not None
    assert mgr.contexts() == []
    assert mgr.describe() == []
    assert mgr.describe(probe=True) == []
    with pytest.raises(KeyError) as ei:
        mgr.get()
    assert "oc login" in str(ei.value)


_KUBECONFIG = """\
apiVersion: v1
kind: Config
current-context: demo
clusters: [{name: demo, cluster: {server: https://127.0.0.1:6443}}]
contexts: [{name: demo, context: {cluster: demo, user: demo}}]
users: [{name: demo, user: {token: t}}]
"""


def test_kubeconfig_appearing_later_recovers_without_restart(tmp_path) -> None:
    path = tmp_path / "kubeconfig"
    cfg = Config(kubeconfig=str(path))
    mgr = ClusterManager.from_config(cfg)  # file not there yet
    assert mgr.unavailable_reason is not None

    path.write_text(_KUBECONFIG)  # `oc login` writes the file

    # next access re-reads the kubeconfig - no new manager, no restart
    assert mgr.unavailable_reason is None
    assert mgr.contexts() == ["demo"]
    assert mgr.default_context == "demo"
