"""Cluster access: construct clients, manage several kubeconfig contexts, and
detect whether a cluster exposes OpenShift APIs.

`ClusterManager` resolves a context name (empty = default) to a `ClusterClient`,
building and caching it on first use. `ClusterClient` is the narrow surface the
toolsets use; tests substitute a fake with the same methods.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config

# Identifies this server as the owner of fields it server-side-applies (shows up
# in metadata.managedFields on the cluster; sanitize.py strips it from responses).
_FIELD_MANAGER = "openshift-mcp-server"
# Synthetic context name used when running from a pod's ServiceAccount (there is
# no kubeconfig, so there are no real context names).
IN_CLUSTER_CONTEXT = "in-cluster"


class ClusterAccess(Protocol):
    """The cluster operations a toolset may call. `ClusterClient` implements it
    against a live cluster; `tests/fakes.py` implements it in memory."""

    name: str

    @property
    def is_openshift(self) -> bool: ...

    def list(
        self,
        api_version: str,
        kind: str,
        *,
        namespace: str | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
        limit: int | None = None,
        continue_token: str | None = None,
    ) -> dict[str, Any]: ...

    def get(
        self, api_version: str, kind: str, name: str, *, namespace: str | None = None
    ) -> dict[str, Any]: ...

    def apply(self, manifest: dict[str, Any]) -> dict[str, Any]: ...

    def delete(
        self, api_version: str, kind: str, name: str, *, namespace: str | None = None
    ) -> dict[str, Any]: ...

    def patch(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str | None,
        merge_patch: dict[str, Any],
    ) -> dict[str, Any]: ...

    def pod_logs(
        self,
        name: str,
        namespace: str,
        *,
        container: str | None = None,
        tail_lines: int | None = None,
        previous: bool = False,
        since_seconds: int | None = None,
    ) -> str: ...

    def instantiate(
        self,
        api_version: str,
        kind: str,
        subresource: str,
        name: str,
        namespace: str | None,
        body: dict[str, Any],
    ) -> dict[str, Any]: ...

    def server_version(self) -> dict[str, Any]: ...


class ClusterClient:
    """Live access to one cluster via direct REST calls on the Kubernetes API.

    Every request carries an explicit timeout and resolving a kind to its REST
    path costs one bounded GET (cached) - no full API discovery, so an
    unreachable API server can never hang a tool call.
    """

    def __init__(self, name: str, api_client: k8s_client.ApiClient, request_timeout: int) -> None:
        """Wrap a configured ``ApiClient``; no network call happens until first use."""
        self.name = name  # context name this client is bound to
        self._api = api_client
        self._timeout = request_timeout
        self._openshift: bool | None = None  # cached result of the OpenShift probe
        # api_version -> {kind -> resource metadata}; populated one group at a
        # time by _resource_meta so we never do a full cluster-wide discovery.
        self._res_cache: dict[str, dict[str, dict[str, Any]]] = {}

    # ---- low-level ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: list[tuple[str, Any]] | None = None,
        body: Any = None,
        content_type: str | None = None,
        timeout: float | tuple[float, float] | None = None,
    ) -> Any:
        """Make one REST call and return the parsed JSON body (``{}`` if empty).

        Single choke point for every request: one place that sets the bearer
        auth, the timeout, and JSON handling. ``_preload_content=False`` keeps
        urllib3 from trying to deserialize with a generated model class.
        """
        headers = {"Accept": "application/json"}
        if content_type:  # only set on writes (apply/merge-patch/JSON POST)
            headers["Content-Type"] = content_type
        resp = self._api.call_api(
            path,
            method.upper(),
            {},  # path params - already baked into `path`
            query or [],
            headers,
            body=body,
            auth_settings=["BearerToken"],  # use the token from the loaded kubeconfig
            _preload_content=False,  # give us the raw response, not a generated model
            _return_http_data_only=True,  # ...and just the body, not (data, status, headers)
            # per-call override wins, else the manager-wide timeout
            _request_timeout=timeout if timeout is not None else self._timeout,
        )
        raw = resp.data
        return json.loads(raw) if raw else {}  # 204 No Content (e.g. some deletes) -> {}

    def _api_root(self, api_version: str) -> str:
        """Map an apiVersion to its URL root: core group ("v1") lives under
        ``/api``; every group version ("apps/v1", ...) under ``/apis``."""
        return f"/api/{api_version}" if "/" not in api_version else f"/apis/{api_version}"

    def _resource_meta(self, api_version: str, kind: str) -> dict[str, Any]:
        """Resolve a kind to its REST metadata: {name: <plural>, namespaced: bool, ...}.

        Costs exactly one GET of the API group the first time that group is
        touched, then serves from cache. Note: the cache never expires, so a CRD
        installed into an already-seen group after startup needs a restart.
        """
        table = self._res_cache.get(api_version)
        if table is None:  # first time we touch this group version - fetch its resource list
            data = self._request("GET", self._api_root(api_version))
            # Index by Kind; several entries can share a Kind (a resource and its
            # subresources), so drop subresources - their "name" has a slash.
            table = {
                r["kind"]: r
                for r in data.get("resources", [])
                if "/" not in r["name"]  # skip subresources like "pods/log", "pods/status"
            }
            self._res_cache[api_version] = table
        meta = table.get(kind)
        if meta is None:  # kind genuinely absent, or the group version is wrong
            raise LookupError(f"{kind} ({api_version}) is not served by this cluster")
        return meta

    def _path(self, api_version: str, kind: str, name: str | None, namespace: str | None) -> str:
        """Build the REST path for a resource, e.g.
        /apis/apps/v1/namespaces/demo/deployments/web  or  /api/v1/nodes."""
        meta = self._resource_meta(api_version, kind)
        path = self._api_root(api_version)
        # Cluster-scoped kinds (Node, Namespace, ...) have no /namespaces/<ns> segment.
        if meta.get("namespaced") and namespace:
            path += f"/namespaces/{namespace}"
        path += f"/{meta['name']}"  # the plural, e.g. "deployments"
        if name:
            path += f"/{name}"
        return path

    # ---- capability probes ----------------------------------------------

    @property
    def is_openshift(self) -> bool:
        """Whether this cluster serves the OpenShift API groups (probed once, then cached)."""
        if self._openshift is None:  # not probed yet
            self._openshift = self._probe_openshift(self._timeout)
        return self._openshift

    def _probe_openshift(self, timeout: float | tuple[float, float]) -> bool:
        """Probe for the ``route.openshift.io`` group; its presence == OpenShift."""
        try:
            # A 2xx here means the group exists -> OpenShift.
            self._request("GET", "/apis/route.openshift.io/v1", timeout=timeout)
            self._openshift = True
        except k8s_client.exceptions.ApiException as exc:
            # 404/403 => group genuinely absent => plain Kubernetes. Any other
            # status (500, timeout wrapped as ApiException, ...) is inconclusive,
            # so assume OpenShift rather than hide the OpenShift tools.
            self._openshift = exc.status not in (404, 403)
        return bool(self._openshift)

    def probe(
        self, timeout: float | tuple[float, float] = 5.0
    ) -> tuple[bool, bool | None, str | None]:
        """Fast (reachable, is_openshift, error) triple for `contexts_list probe=true`.

        `/version` needs no RBAC, so it is a clean reachability signal. Returns
        early with the error string if the cluster can't be reached at all.
        """
        try:
            self._request("GET", "/version", timeout=timeout)  # unauthenticated reachability check
        except Exception as exc:
            return False, None, str(exc)  # can't even reach it - report why
        try:
            return True, self._probe_openshift(timeout), None  # reachable + classified
        except Exception:
            return True, None, None  # reachable, but couldn't classify it

    def server_version(self) -> dict[str, Any]:
        """Return the cluster's ``/version`` payload (also the readiness-probe call)."""
        return self._request("GET", "/version")

    # ---- resource operations ------------------------------------------

    def list(
        self,
        api_version: str,
        kind: str,
        *,
        namespace: str | None = None,
        label_selector: str | None = None,
        field_selector: str | None = None,
        limit: int | None = None,
        continue_token: str | None = None,
    ) -> dict[str, Any]:
        """GET a ``<kind>List``. `namespace=None` lists across all namespaces
        (``_path`` omits the namespace segment); the other args map to the
        standard list query params."""
        query: list[tuple[str, Any]] = []
        # Each arg becomes a query param only when set - an empty selector would
        # match nothing, and limit=0 means "no limit" which we never want here.
        if label_selector:
            query.append(("labelSelector", label_selector))
        if field_selector:
            query.append(("fieldSelector", field_selector))
        if limit:
            query.append(("limit", limit))
        if continue_token:  # opaque token from a previous response's metadata.continue
            query.append(("continue", continue_token))
        # name=None -> _path stops at the plural, i.e. this is a collection GET
        return self._request("GET", self._path(api_version, kind, None, namespace), query=query)

    def get(
        self, api_version: str, kind: str, name: str, *, namespace: str | None = None
    ) -> dict[str, Any]:
        """GET a single named resource."""
        return self._request("GET", self._path(api_version, kind, name, namespace))

    def apply(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Server-side apply a full manifest (a PATCH with the apply content-type).

        ``force=true`` takes ownership of fields another manager set, so
        re-applying a tweaked manifest doesn't 409 on a field-manager conflict.
        """
        meta = manifest.get("metadata", {})
        # Address the object from its own apiVersion/kind/metadata (caller-supplied).
        path = self._path(
            manifest["apiVersion"], manifest["kind"], meta.get("name"), meta.get("namespace")
        )
        return self._request(
            "PATCH",
            path,
            # fieldManager tags the fields we own; force=true resolves conflicts in our favour
            query=[("fieldManager", _FIELD_MANAGER), ("force", "true")],
            body=manifest,
            content_type="application/apply-patch+yaml",  # JSON body is valid apply-patch YAML
        )

    def delete(
        self, api_version: str, kind: str, name: str, *, namespace: str | None = None
    ) -> dict[str, Any]:
        """DELETE a single named resource."""
        return self._request("DELETE", self._path(api_version, kind, name, namespace))

    def patch(
        self,
        api_version: str,
        kind: str,
        name: str,
        namespace: str | None,
        merge_patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply a JSON merge patch (RFC 7386): `merge_patch` is a sparse object
        merged into the resource. Used by ``resources_scale`` and
        ``workloads_restart``."""
        return self._request(
            "PATCH",
            self._path(api_version, kind, name, namespace),
            body=merge_patch,
            content_type="application/merge-patch+json",
        )

    def instantiate(
        self,
        api_version: str,
        kind: str,
        subresource: str,
        name: str,
        namespace: str | None,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """POST `body` to an action subresource, e.g.
        ``.../buildconfigs/<name>/instantiate`` (``builds_trigger`` -> a new Build)."""
        path = self._path(api_version, kind, name, namespace) + f"/{subresource}"
        return self._request("POST", path, body=body, content_type="application/json")

    def pod_logs(
        self,
        name: str,
        namespace: str,
        *,
        container: str | None = None,
        tail_lines: int | None = None,
        previous: bool = False,
        since_seconds: int | None = None,
    ) -> str:
        """Fetch a pod's container logs as plain text.

        The ``pods/log`` subresource returns text, not JSON, so this bypasses
        ``_request`` and asks for ``text/plain`` directly.
        """
        query: list[tuple[str, Any]] = []
        if container:  # required when the pod has more than one container
            query.append(("container", container))
        if tail_lines:
            query.append(("tailLines", tail_lines))
        if previous:  # logs from the last crashed instance rather than the running one
            query.append(("previous", "true"))
        if since_seconds:
            query.append(("sinceSeconds", since_seconds))
        # call_api directly (not _request): this endpoint returns text/plain, not JSON
        resp = self._api.call_api(
            f"/api/v1/namespaces/{namespace}/pods/{name}/log",
            "GET",
            {},
            query,
            {"Accept": "text/plain"},
            auth_settings=["BearerToken"],
            _preload_content=False,
            _return_http_data_only=True,
            _request_timeout=self._timeout,
        )
        return resp.data.decode("utf-8", "replace")  # never blow up on odd bytes in a log


@dataclass(frozen=True, slots=True)
class ContextInfo:
    """One row of ``contexts_list`` output: a kubeconfig context and, when
    ``probe=true`` was passed, what probing it found."""

    name: str
    default: bool
    reachable: bool | None = None  # None = not probed
    openshift: bool | None = None
    error: str | None = None


def _in_cluster_available() -> bool:
    """True when running inside a pod with a mounted ServiceAccount token -
    both the injected env var and the token file must be present."""
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and os.path.exists(
        "/var/run/secrets/kubernetes.io/serviceaccount/token"
    )


class ClusterManager:
    """Owns one lazily-built ClusterClient per context, keyed by context name.

    Empty name -> the default context. Building/caching is concurrency-safe;
    a failed build is not cached, so a transiently-unreachable cluster recovers.

    The kubeconfig is re-read whenever the file changes on disk (see
    ``_maybe_reload``), so an ``oc login`` after the server started - a fresh
    login, a switched context, or a refreshed token - is picked up automatically
    with no restart.
    """

    def __init__(
        self,
        contexts: list[str],
        default_context: str,
        *,
        kubeconfig: str | None,
        in_cluster: bool,
        request_timeout: int,
        unavailable_reason: str | None = None,
        cfg: Any = None,
    ) -> None:
        """Store the resolved context list. Prefer the ``from_*`` classmethods.

        ``unavailable_reason`` set: the server has no usable credentials (no
        kubeconfig, unreadable file, ...). Construct anyway so the MCP client
        stays connected; cluster tools raise a clean error until it is fixed.
        ``cfg`` is kept so the kubeconfig can be re-resolved later on change.
        """
        if unavailable_reason is None:  # a "real" manager - the invariants must hold
            if not contexts:
                raise ValueError("no contexts configured")
            if default_context not in contexts:
                raise ValueError(f"default context {default_context!r} is not one of {contexts}")
        self._order = list(contexts)  # context names, in kubeconfig order
        self._default = default_context
        self._kubeconfig = kubeconfig  # path (or None for in-cluster) - passed to _build
        self._in_cluster = in_cluster
        self._timeout = request_timeout
        self._unavailable_reason = unavailable_reason
        self._cfg = cfg  # kept for _maybe_reload; None for from_clients (tests)
        self._clients: dict[str, ClusterClient] = {}  # context -> client, filled on first use
        self._lock = threading.Lock()  # guards _clients (tool calls run on many threads)
        # fingerprint of the kubeconfig file(s) now, so _maybe_reload can spot a change
        self._kubeconfig_sig = self._kubeconfig_signature() if cfg is not None else None

    @classmethod
    def from_config(cls, cfg: Any) -> ClusterManager:
        """Build a manager from a `config.Config` (typed as Any to avoid an import cycle)."""
        # In-cluster mode: forced by --in-cluster, or auto when there is no
        # kubeconfig but we are clearly running in a pod. One synthetic context.
        if cfg.in_cluster or (not cfg.kubeconfig and _in_cluster_available()):
            return cls(
                [IN_CLUSTER_CONTEXT],
                IN_CLUSTER_CONTEXT,
                kubeconfig=None,
                in_cluster=True,
                request_timeout=cfg.request_timeout,
            )
        # Otherwise: every context in the kubeconfig is selectable. A missing or
        # broken kubeconfig is not fatal - start in the "unavailable" state (the
        # MCP client stays connected) and recover on the next _maybe_reload.
        order, default, reason = cls._resolve(cfg)
        return cls(
            order,
            default,
            kubeconfig=cfg.kubeconfig,
            in_cluster=False,
            request_timeout=cfg.request_timeout,
            unavailable_reason=reason,
            cfg=cfg,
        )

    @staticmethod
    def _resolve(cfg: Any) -> tuple[list[str], str, str | None]:
        """Read the kubeconfig -> (context names, default context, unavailable_reason).

        ``unavailable_reason`` is None on success; on any failure (no file,
        unreadable, empty, bad --context) it is the message and the two lists
        come back empty.
        """
        try:
            # (all contexts, the current-context entry) from the kubeconfig
            raw, active = k8s_config.list_kube_config_contexts(config_file=cfg.kubeconfig)
            names = [c["name"] for c in raw]
            if not names:
                raise ValueError("kubeconfig has no contexts")
            # Default context: --context wins, else the file's current-context, else the first.
            default = cfg.context or (active or {}).get("name") or names[0]
            if default not in names:
                raise ValueError(
                    f"context {default!r} not found in kubeconfig (have: {', '.join(names)})"
                )
            return names, default, None
        except Exception as exc:
            return [], "", (str(exc) or exc.__class__.__name__)

    def _kubeconfig_signature(self) -> tuple[tuple[str, float | None], ...] | None:
        """(path, mtime-or-None) for each effective kubeconfig file.

        Changes when ``oc login`` rewrites the file (new token / new context) or
        when a previously-missing file appears. None for in-cluster mode.
        """
        if self._in_cluster:
            return None
        if self._kubeconfig:  # explicit --kubeconfig / KUBECONFIG / MCP_KUBECONFIG
            paths = self._kubeconfig.split(os.pathsep)
        elif os.environ.get("KUBECONFIG"):
            paths = os.environ["KUBECONFIG"].split(os.pathsep)
        else:
            paths = [os.path.expanduser("~/.kube/config")]
        out: list[tuple[str, float | None]] = []
        for p in paths:
            try:
                out.append((p, os.path.getmtime(p)))
            except OSError:
                out.append((p, None))  # not there (yet)
        return tuple(out)

    def _maybe_reload(self) -> None:
        """Re-resolve the kubeconfig if it changed on disk since we last looked.

        Cheap (a stat per file) on the common no-change path. On a change it
        refreshes the context list / unavailable state and drops every cached
        client so the next call rebuilds with the current server + token.
        """
        if self._cfg is None or self._in_cluster:
            return
        sig = self._kubeconfig_signature()
        if sig == self._kubeconfig_sig:
            return  # unchanged - nothing to do
        order, default, reason = self._resolve(self._cfg)
        with self._lock:
            self._kubeconfig_sig = sig
            self._order = order
            self._default = default
            self._unavailable_reason = reason
            self._clients.clear()  # tokens / API servers may have changed

    @classmethod
    def from_clients(cls, clients: dict[str, Any], default_context: str) -> ClusterManager:
        """Build a manager backed by ready-made clients. For tests."""
        mgr = cls(
            list(clients),
            default_context,
            kubeconfig=None,
            in_cluster=False,
            request_timeout=30,
        )
        mgr._clients = dict(clients)  # pre-populate the cache so _build is never called
        return mgr

    @property
    def default_context(self) -> str:
        """Context used when a tool call omits ``context`` (``""`` when unavailable)."""
        self._maybe_reload()
        return self._default

    @property
    def unavailable_reason(self) -> str | None:
        """Non-None when the server has no usable cluster credentials."""
        self._maybe_reload()
        return self._unavailable_reason

    def contexts(self) -> list[str]:
        """The selectable context names, in kubeconfig order (``[]`` when unavailable)."""
        self._maybe_reload()
        return list(self._order)

    def _build(self, name: str) -> ClusterClient:
        """Construct (but do not connect) a ClusterClient for one context."""
        conf = k8s_client.Configuration()
        # Populate `conf` (server URL, CA, token) from the right credential source...
        if self._in_cluster:
            k8s_config.load_incluster_config(client_configuration=conf)
        else:
            # ...or from this specific kubeconfig context (not the file's current-context)
            k8s_config.load_kube_config(
                config_file=self._kubeconfig, context=name, client_configuration=conf
            )
        conf.retries = 1  # urllib3 retries default to 3 - don't triple the latency of a dead API
        # ApiClient is just an HTTP wrapper here; no connection opens until first request.
        return ClusterClient(name, k8s_client.ApiClient(configuration=conf), self._timeout)

    def get(self, context: str | None = None) -> ClusterClient:
        """Return the ClusterClient for `context` (None -> default), building it once.

        Raises KeyError for an unknown context name; errors.tool_error turns that
        into a clean message. A failed _build is NOT cached, so a cluster that was
        briefly unreachable at first use can still recover later.
        """
        self._maybe_reload()  # pick up an `oc login` since startup
        if self._unavailable_reason is not None:
            raise KeyError(
                f"no cluster access: {self._unavailable_reason}. Run `oc login` "
                f"(or set --kubeconfig / --in-cluster); no server restart needed."
            )
        name = context or self._default  # "" / None both mean "the default context"
        if name not in self._order:
            raise KeyError(f"unknown context {name!r} (configured: {', '.join(self._order)})")
        with self._lock:  # fast path: already built
            cached = self._clients.get(name)
        if cached is not None:
            return cached
        built = self._build(name)  # outside the lock: building may do disk I/O
        with self._lock:
            # setdefault: if another thread built it while we were, keep theirs
            # so every caller for this context shares one client (and its caches).
            self._clients.setdefault(name, built)
            return self._clients[name]

    def describe(self, *, probe: bool = False, probe_timeout: float = 4.0) -> list[ContextInfo]:
        """Status of every configured context. probe=False (default) does no I/O
        - just names and which is default. probe=True checks reachability +
        OpenShift for each, concurrently and time-bounded."""
        self._maybe_reload()  # pick up an `oc login` since startup
        if not self._order:  # no credentials configured -> nothing to describe
            return []
        if not probe:  # cheap path: names + which is default, no network
            return [ContextInfo(n, n == self._default) for n in self._order]

        def _one(name: str) -> ContextInfo:
            """Probe one context; never raises - failures become error rows."""
            is_default = name == self._default
            try:
                reachable, openshift, err = self.get(name).probe(probe_timeout)
            except Exception as exc:
                # e.g. the kubeconfig entry itself is broken (bad cert path)
                return ContextInfo(name, is_default, False, None, str(exc))
            return ContextInfo(name, is_default, reachable, openshift, err)

        # Probe every context in parallel so N unreachable clusters cost one
        # timeout, not N. Each probe is already time-bounded by probe_timeout.
        with ThreadPoolExecutor(max_workers=min(8, len(self._order))) as pool:
            return list(pool.map(_one, self._order))
