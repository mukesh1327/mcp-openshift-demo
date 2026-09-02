"""openshift toolset: OpenShift-specific conveniences on top of the generic
resource tools. Registered only when a target cluster exposes OpenShift APIs.
"""

from __future__ import annotations

import datetime as _dt
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import ToolError, tool_error
from . import Deps, clamp_limit, serialize

_RO = ToolAnnotations(read_only_hint=True)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)

Ctx = Annotated[
    str | None,
    Field(description="target context name (see contexts_list); omit for the default context"),
]

_RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"


def register(server: Any, deps: Deps) -> None:
    cfg = deps.cfg
    mgr = deps.manager

    def _client(context: str | None) -> Any:
        try:
            client = mgr.get(context or None)
        except KeyError as exc:
            raise tool_error("selecting cluster", exc) from exc
        try:
            openshift = client.is_openshift
        except Exception:
            openshift = True
        if not openshift:
            name = context or mgr.default_context
            raise ToolError(
                f"context {name!r} is not an OpenShift cluster "
                f"(the route.openshift.io API group is absent); this tool is OpenShift-only"
            )
        return client

    def _out(payload: Any) -> str:
        return serialize(payload, cfg.list_output)

    def projects_list(context: Ctx = None) -> str:
        """List OpenShift Projects visible to the credentials (respects project
        visibility, unlike listing Namespaces)."""
        client = _client(context)
        try:
            payload = client.list(
                "project.openshift.io/v1", "Project", limit=clamp_limit(None, cfg)
            )
        except Exception as exc:
            raise tool_error("listing projects", exc) from exc
        return _out(payload)

    def routes_list(
        namespace: Annotated[str, Field(description="namespace to list routes in")],
        label_selector: Annotated[str | None, Field(description="label selector")] = None,
        context: Ctx = None,
    ) -> str:
        """List Routes in a namespace, including their external hosts."""
        client = _client(context)
        try:
            payload = client.list(
                "route.openshift.io/v1",
                "Route",
                namespace=namespace,
                label_selector=label_selector,
                limit=clamp_limit(None, cfg),
            )
        except Exception as exc:
            raise tool_error(f"listing routes in namespace {namespace}", exc) from exc
        return _out(payload)

    server.add_tool(
        projects_list,
        name="projects_list",
        description="Read-only. OpenShift only. List Projects.",
        annotations=_RO,
    )
    server.add_tool(
        routes_list,
        name="routes_list",
        description="Read-only. OpenShift only. List Routes with their hosts.",
        annotations=_RO,
    )

    if cfg.read_only:
        return

    def workloads_restart(
        name: Annotated[str, Field(description="workload name")],
        namespace: Annotated[str, Field(description="namespace containing the workload")],
        kind: Annotated[str, Field(description="Deployment or DeploymentConfig")] = "Deployment",
        api_version: Annotated[str, Field(description="apiVersion of the workload")] = "apps/v1",
        context: Ctx = None,
    ) -> str:
        """Trigger a rolling restart by touching the pod template's restart
        annotation (like ``kubectl rollout restart``). Does not change replicas."""
        client = _client(context)
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        patch = {"spec": {"template": {"metadata": {"annotations": {_RESTART_ANNOTATION: stamp}}}}}
        try:
            payload = client.patch(api_version, kind, name, namespace, patch)
        except Exception as exc:
            raise tool_error(f"restarting {kind}/{name}", exc) from exc
        return _out(payload)

    def builds_trigger(
        name: Annotated[str, Field(description="BuildConfig name to start a Build from")],
        namespace: Annotated[str, Field(description="namespace containing the BuildConfig")],
        commit_ref: Annotated[
            str | None, Field(description="git commit SHA or ref to build instead of the default")
        ] = None,
        context: Ctx = None,
    ) -> str:
        """Start a new Build from a BuildConfig (like ``oc start-build``).
        Creates exactly one Build; does not modify the BuildConfig."""
        client = _client(context)
        body: dict[str, Any] = {
            "kind": "BuildRequest",
            "apiVersion": "build.openshift.io/v1",
            "metadata": {"name": name},
        }
        if commit_ref:
            body["revision"] = {"type": "Git", "git": {"commit": commit_ref}}
        try:
            payload = client.instantiate(
                "build.openshift.io/v1", "BuildConfig", "instantiate", name, namespace, body
            )
        except Exception as exc:
            raise tool_error(f"triggering build from buildconfig {namespace}/{name}", exc) from exc
        return _out(payload)

    server.add_tool(
        workloads_restart,
        name="workloads_restart",
        description="Write. OpenShift/K8s. Rolling-restart a Deployment or DeploymentConfig.",
        annotations=_WRITE,
    )
    server.add_tool(
        builds_trigger,
        name="builds_trigger",
        description="Write. OpenShift only. Start a new Build from a BuildConfig.",
        annotations=_WRITE,
    )
