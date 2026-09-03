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

# Setting this template annotation to a fresh value is exactly what
# `kubectl rollout restart` does - it changes the pod spec hash, triggering a
# rolling replacement without touching replicas or the image.
_RESTART_ANNOTATION = "kubectl.kubernetes.io/restartedAt"


def register(server: Any, deps: Deps) -> None:
    """Register the OpenShift tools (reads always; the two writes only without --read-only).

    Every handler here goes through the OpenShift-gated ``_client`` below, so a
    call against a plain-Kubernetes context fails fast with a clear message.
    """
    cfg = deps.cfg
    mgr = deps.manager

    def _client(context: str | None) -> Any:
        """Resolve `context` to a ClusterClient, refusing non-OpenShift clusters.

        Same as core's ``_client``, plus an OpenShift gate: these tools use
        OpenShift-only APIs, so refuse early (with a clear message) on a
        plain-Kubernetes context rather than returning a raw 404 later.
        """
        try:
            client = mgr.get(context or None)  # bad name / no creds -> KeyError
        except KeyError as exc:
            raise tool_error("selecting cluster", exc) from exc
        try:
            openshift = client.is_openshift  # one cached probe of route.openshift.io
        except Exception:
            openshift = True  # probe failed/inconclusive - don't block the call
        if not openshift:  # definitively plain Kubernetes -> these tools can't work
            name = context or mgr.default_context
            raise ToolError(
                f"context {name!r} is not an OpenShift cluster "
                f"(the route.openshift.io API group is absent); this tool is OpenShift-only"
            )
        return client

    def _out(payload: Any) -> str:
        """Sanitize and render a cluster object as the tool's text result."""
        return serialize(payload, cfg.list_output)

    def projects_list(context: Ctx = None) -> str:
        """List OpenShift Projects visible to the credentials.

        Prefer this over `resources_list Namespace`: the projects API filters to
        what the caller may see, whereas listing Namespaces needs cluster-wide
        read and returns everything.
        """
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

    # --read-only stops here; the two write tools below are not registered.
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
        # A new timestamp every call guarantees the annotation actually changes,
        # which changes the pod-template hash and makes the controller roll pods.
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Sparse patch: only spec.template.metadata.annotations[...] is touched.
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
        # A BuildRequest POSTed to buildconfigs/<name>/instantiate is the API
        # behind `oc start-build`; the cluster creates one Build and returns it.
        body: dict[str, Any] = {
            "kind": "BuildRequest",
            "apiVersion": "build.openshift.io/v1",
            "metadata": {"name": name},  # must match the BuildConfig being instantiated
        }
        if commit_ref:  # build a specific git revision instead of the BuildConfig default
            body["revision"] = {"type": "Git", "git": {"commit": commit_ref}}
        try:
            # POST .../buildconfigs/<name>/instantiate -> the cluster returns the new Build
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
