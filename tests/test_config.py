"""config.load: defaults, the TOML < env < CLI precedence chain, and validation."""

from __future__ import annotations

import dataclasses

import pytest

from openshift_mcp.config import Config, load


def test_defaults() -> None:
    cfg = load([], environ={})
    assert cfg.transport == "stdio"
    assert cfg.read_only is False
    assert cfg.disable_destructive is True
    assert cfg.toolsets == ("core", "config", "openshift")
    assert cfg.list_limit == 200


def test_precedence_env_then_flag(tmp_path) -> None:
    toml = tmp_path / "s.toml"
    toml.write_text("list_limit = 10\ntransport = 'http'\n")

    # TOML < env
    cfg = load(["--config", str(toml)], environ={"MCP_LIST_LIMIT": "20"})
    assert cfg.list_limit == 20
    assert cfg.transport == "http"

    # env < flag
    cfg = load(
        ["--config", str(toml), "--list-limit", "30"],
        environ={"MCP_LIST_LIMIT": "20"},
    )
    assert cfg.list_limit == 30


def test_kubeconfig_env_fallback() -> None:
    cfg = load([], environ={"KUBECONFIG": "/home/me/kc"})
    assert cfg.kubeconfig == "/home/me/kc"


def test_toolsets_parsing() -> None:
    cfg = load(["--toolsets", "core, config"], environ={})
    assert cfg.toolsets == ("core", "config")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: {"transport": "carrier-pigeon"},
        lambda c: {"port": 0},
        lambda c: {"list_limit": -1},
        lambda c: {"toolsets": ("core", "bogus")},
        lambda c: {"list_output": "xml"},
    ],
)
def test_validate_rejects(mutate) -> None:
    with pytest.raises(ValueError):
        dataclasses.replace(Config(), **mutate(None)).validate()


def test_boolean_optional_actions() -> None:
    assert load(["--read-only"], environ={}).read_only is True
    assert load(["--no-disable-destructive"], environ={}).disable_destructive is False
