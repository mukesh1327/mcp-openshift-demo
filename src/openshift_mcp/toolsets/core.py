"""core toolset: generic resource operations plus a few specials.

One generic ``resources_*`` family works on any GVK (Pod, Deployment, Route,
DeploymentConfig, CRDs, ...) instead of a tool per kind. ``pods_log`` and
``events_list`` stay dedicated because they are subresource / ordering
specials.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import ToolError, tool_error
from . import Deps, clamp_limit, clamp_tail, serialize

_RO = ToolAnnotations(read_only_hint=True)
_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False)
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)

Ctx = Annotated[
    str | None,
    Field(description="target context name (see contexts_list); omit for the default context"),
]
Kind = Annotated[
    str, Field(description="resource kind, e.g. Pod, Deployment, Route, DeploymentConfig")
]
ApiVersion = Annotated[
    str,
    Field(description="apiVersion, e.g. v1, apps/v1, route.openshift.io/v1, apps.openshift.io/v1"),
]
Namespace = Annotated[
    str | None, Field(description="namespace; omit only for cluster-scoped kinds")
]


def register(server: Any, deps: Deps) -> None:
    cfg = deps.cfg
    mgr = deps.manager

    def _client(context: str | None) -> Any:
        try:
            return mgr.get(context or None)
        except KeyError as exc:
            raise tool_error("selecting cluster", exc) from exc

    def _out(payload: Any) -> str:
        return serialize(payload, cfg.list_output)

    # ---- reads -----------------------------------------------------------

    def resources_list(
        kind: Kind,
        api_version: ApiVersion = "v1",
        namespace: Namespace = None,
        label_selector: Annotated[
            str | None, Field(description="label selector, e.g. app=frontend")
        ] = None,
        field_selector: Annotated[
            str | None, Field(description="field selector, e.g. status.phase=Running")
        ] = None,
        limit: Annotated[int | None, Field(description="max items (server-capped)")] = None,
        continue_token: Annotated[
            str | None,
            Field(description="pagination token from a previous call's metadata.continue"),
        ] = None,
        context: Ctx = None,
    ) -> str:
        """List resources of any kind, optionally filtered by namespace and selectors."""
        client = _client(context)
        try:
            payload = client.list(
                api_version,
                kind,
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
                limit=clamp_limit(limit, cfg),
                continue_token=continue_token,
            )
        except Exception as exc:
            raise tool_error(f"listing {kind}", exc) from exc
        return _out(payload)

    def resources_get(
        kind: Kind,
        name: Annotated[str, Field(description="resource name")],
        api_version: ApiVersion = "v1",
        namespace: Namespace = None,
        context: Ctx = None,
    ) -> str:
        """Get one resource of any kind as full structured JSON/YAML."""
        client = _client(context)
        try:
            payload = client.get(api_version, kind, name, namespace=namespace)
        except Exception as exc:
            raise tool_error(f"getting {kind}/{name}", exc) from exc
        return _out(payload)

    def pods_log(
        name: Annotated[str, Field(description="pod name")],
        namespace: Annotated[str, Field(description="namespace containing the pod")],
        container: Annotated[
            str | None, Field(description="container name; required for multi-container pods")
        ] = None,
        tail_lines: Annotated[
            int | None, Field(description="lines from the end (server-capped)")
        ] = None,
        previous: Annotated[
            bool, Field(description="logs from the previous terminated container instance")
        ] = False,
        since_seconds: Annotated[
            int | None, Field(description="only logs newer than this many seconds")
        ] = None,
        context: Ctx = None,
    ) -> str:
        """Fetch recent container logs for a pod (tail-capped)."""
        client = _client(context)
        try:
            return client.pod_logs(
                name,
                namespace,
                container=container,
                tail_lines=clamp_tail(tail_lines, cfg),
                previous=previous,
                since_seconds=since_seconds,
            )
        except Exception as exc:
            raise tool_error(f"getting logs for pod {namespace}/{name}", exc) from exc

    def events_list(
        namespace: Annotated[str, Field(description="namespace to list events in")],
        field_selector: Annotated[
            str | None, Field(description="field selector, e.g. involvedObject.name=my-pod")
        ] = None,
        limit: Annotated[int | None, Field(description="max events, most recent first")] = None,
        context: Ctx = None,
    ) -> str:
        """List recent events in a namespace, most recent first."""
        client = _client(context)
        try:
            payload = client.list(
                "v1",
                "Event",
                namespace=namespace,
                field_selector=field_selector,
                limit=clamp_limit(None, cfg),
            )
        except Exception as exc:
            raise tool_error(f"listing events in namespace {namespace}", exc) from exc
        items = payload.get("items", [])
        items.sort(key=_event_timestamp, reverse=True)
        payload["items"] = items[: clamp_limit(limit, cfg)]
        return _out(payload)

    for fn, name, desc in (
        (resources_list, "resources_list", "Read-only. List resources of any kind."),
        (resources_get, "resources_get", "Read-only. Get one resource of any kind."),
        (pods_log, "pods_log", "Read-only. Recent container logs for a pod."),
        (events_list, "events_list", "Read-only. Recent events in a namespace, newest first."),
    ):
        server.add_tool(fn, name=name, description=desc, annotations=_RO)

    if cfg.read_only:
        return

    # ---- non-destructive writes ----------------------------------------

    def resources_apply(
        manifest: Annotated[
            dict[str, Any],
            Field(description="full resource manifest (apiVersion, kind, metadata, spec)"),
        ],
        context: Ctx = None,
    ) -> str:
        """Create or update a resource via server-side apply."""
        client = _client(context)
        name = manifest.get("metadata", {}).get("name") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or not all(manifest.get(k) for k in ("apiVersion", "kind"))
            or not name
        ):
            raise ToolError("applying resource: manifest needs apiVersion, kind and metadata.name")
        ident = f"{manifest['kind']}/{name}"
        try:
            payload = client.apply(manifest)
        except Exception as exc:
            raise tool_error(f"applying {ident}", exc) from exc
        return _out(payload)

    def resources_scale(
        kind: Annotated[
            str, Field(description="workload kind: Deployment, StatefulSet, DeploymentConfig")
        ],
        name: Annotated[str, Field(description="workload name")],
        namespace: Annotated[str, Field(description="namespace containing the workload")],
        replicas: Annotated[int, Field(description="desired replica count (>= 0)", ge=0, le=500)],
        api_version: ApiVersion = "apps/v1",
        context: Ctx = None,
    ) -> str:
        """Scale a workload to an explicit replica count."""
        client = _client(context)
        try:
            payload = client.patch(
                api_version, kind, name, namespace, {"spec": {"replicas": replicas}}
            )
        except Exception as exc:
            raise tool_error(f"scaling {kind}/{name}", exc) from exc
        return _out(payload)

    server.add_tool(
        resources_apply,
        name="resources_apply",
        description="Write. Create or update any resource via server-side apply.",
        annotations=_WRITE,
    )
    server.add_tool(
        resources_scale,
        name="resources_scale",
        description="Write. Scale a workload to an explicit replica count.",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )

    if cfg.disable_destructive:
        return

    # ---- destructive --------------------------------------------------

    def resources_delete(
        kind: Kind,
        name: Annotated[str, Field(description="resource name")],
        api_version: ApiVersion = "v1",
        namespace: Namespace = None,
        context: Ctx = None,
    ) -> str:
        """Delete a resource."""
        client = _client(context)
        try:
            payload = client.delete(api_version, kind, name, namespace=namespace)
        except Exception as exc:
            raise tool_error(f"deleting {kind}/{name}", exc) from exc
        return _out(payload)

    server.add_tool(
        resources_delete,
        name="resources_delete",
        description="Destructive. Delete a resource. Needs writes + no --disable-destructive.",
        annotations=_DESTRUCTIVE,
    )


def _event_timestamp(event: dict[str, Any]) -> str:
    return (
        event.get("lastTimestamp")
        or event.get("eventTime")
        or event.get("deprecatedLastTimestamp")
        or (event.get("metadata") or {}).get("creationTimestamp")
        or ""
    )
