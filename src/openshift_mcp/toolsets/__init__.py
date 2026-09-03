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
    """The shared context handed to every toolset's ``register()``.

    Bundles the cluster manager, the effective config, and a logger so tool
    handlers reach them by closure instead of module-level global state.
    """

    manager: ClusterManager
    cfg: Config
    log: logging.Logger


def serialize(payload: Any, fmt: str) -> str:
    """Sanitize a cluster API object and render it as the text an MCP tool returns.

    Strings (pod logs) pass through untouched. Dicts are cleaned by sanitize()
    then dumped as pretty JSON or YAML per --list-output. `default=str` keeps
    json.dumps from choking on stray datetimes.
    """
    payload = sanitize(payload)  # strip managedFields etc. before it ever hits the wire
    if isinstance(payload, str):
        return payload  # a pod log - already text, don't JSON-encode it
    if fmt == "yaml":
        # sort_keys=False keeps k8s field order (apiVersion, kind, metadata, spec...)
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)
    return json.dumps(payload, indent=2, default=str)  # default=str: tolerate datetimes


def clamp_limit(requested: int | None, cfg: Config) -> int:
    """Cap a caller-supplied list size at --list-limit (also the default when unset/<=0)."""
    # None / 0 / negative / over-cap all collapse to the configured maximum;
    # only an explicit value within (0, list_limit] is passed through as-is.
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
    # Local imports: keep `import openshift_mcp.toolsets` cheap and cycle-free.
    from . import config as config_toolset
    from . import core as core_toolset
    from . import openshift as openshift_toolset

    # cfg.toolsets was validated in Config.validate(), so every name here is known.
    enabled = set(deps.cfg.toolsets)
    if "core" in enabled:
        core_toolset.register(server, deps)
    if "config" in enabled:
        config_toolset.register(server, deps)
    if "openshift" in enabled:
        # Note: this registers the OpenShift tools unconditionally; each one still
        # checks is_openshift at call time and refuses on a plain-k8s context.
        openshift_toolset.register(server, deps)
