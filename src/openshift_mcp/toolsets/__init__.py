"""Toolsets: modular groups of MCP tools, enabled via ``--toolsets``.

core      resources_list/get/apply/scale/delete, pods_log, events_list
config    contexts_list, configuration_view
openshift projects_list, routes_list, workloads_restart, builds_trigger
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import yaml

from ..config import Config
from ..k8s import ClusterManager
from ..sanitize import sanitize

KNOWN = ("core", "config", "openshift")


# One bundle passed to every toolset's register() so tool handlers can reach the
# cluster manager, the effective config, and a logger without global state.
@dataclass(slots=True)
class Deps:
    manager: ClusterManager
    cfg: Config
    log: logging.Logger


def serialize(payload: Any, fmt: str) -> str:
    """Sanitize a cluster API object and render it as the text an MCP tool returns.

    Strings (pod logs) pass through untouched. Dicts are cleaned by sanitize()
    then dumped as pretty JSON or YAML per --list-output. `default=str` keeps
    json.dumps from choking on stray datetimes.
    """
    payload = sanitize(payload)
    if isinstance(payload, str):
        return payload
    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    return json.dumps(payload, indent=2, default=str)


def clamp_limit(requested: int | None, cfg: Config) -> int:
    """Cap a caller-supplied list size at --list-limit (also the default when unset/<=0)."""
    if not requested or requested <= 0 or requested > cfg.list_limit:
        return cfg.list_limit
    return requested


def clamp_tail(requested: int | None, cfg: Config) -> int:
    """Same idea as clamp_limit but for pod-log lines (--log-max-lines)."""
    if not requested or requested <= 0 or requested > cfg.log_max_lines:
        return cfg.log_max_lines
    return requested


def register_all(server: Any, deps: Deps) -> None:
    """Attach every enabled toolset's tools to the server.

    Imports are local so importing this package doesn't drag in all three
    toolset modules. Each toolset's own register() applies the finer gates
    (--read-only, --disable-destructive).
    """
    from . import config as config_toolset
    from . import core as core_toolset
    from . import openshift as openshift_toolset

    enabled = set(deps.cfg.toolsets)
    if "core" in enabled:
        core_toolset.register(server, deps)
    if "config" in enabled:
        config_toolset.register(server, deps)
    if "openshift" in enabled:
        openshift_toolset.register(server, deps)
