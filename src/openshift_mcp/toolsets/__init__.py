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


@dataclass(slots=True)
class Deps:
    manager: ClusterManager
    cfg: Config
    log: logging.Logger


def serialize(payload: Any, fmt: str) -> str:
    """Sanitize and render a cluster API object as text for the model."""
    payload = sanitize(payload)
    if isinstance(payload, str):
        return payload
    if fmt == "yaml":
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    return json.dumps(payload, indent=2, default=str)


def clamp_limit(requested: int | None, cfg: Config) -> int:
    if not requested or requested <= 0 or requested > cfg.list_limit:
        return cfg.list_limit
    return requested


def clamp_tail(requested: int | None, cfg: Config) -> int:
    if not requested or requested <= 0 or requested > cfg.log_max_lines:
        return cfg.log_max_lines
    return requested


def register_all(server: Any, deps: Deps) -> None:
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
