"""In-memory doubles implementing the ClusterAccess surface."""

from __future__ import annotations

from typing import Any

from kubernetes.client.exceptions import ApiException


class FakeCluster:
    """A ClusterAccess implementation that records calls and returns canned data."""

    def __init__(self, name: str = "default", *, openshift: bool = True) -> None:
        self.name = name
        self.is_openshift = openshift
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []  # every op, in order
        self.raise_on: dict[str, BaseException] = {}  # op name -> exception to raise from it
        self.objects: dict[tuple[str, str | None], dict[str, Any]] = {}  # (kind, ns) -> canned get

    def _record(self, op: str, *args: Any, **kwargs: Any) -> None:
        # Log the call for assertions, then optionally simulate a cluster failure.
        self.calls.append((op, args, kwargs))
        if op in self.raise_on:
            raise self.raise_on[op]

    def list(self, api_version: str, kind: str, **kwargs: Any) -> dict[str, Any]:
        self._record("list", api_version, kind, **kwargs)
        # The single item carries managedFields + a noise annotation on purpose,
        # so tests can assert sanitize() stripped them.
        return {
            "apiVersion": api_version,
            "kind": f"{kind}List",
            "metadata": {"resourceVersion": "1", "continue": ""},
            "items": [
                {
                    "apiVersion": api_version,
                    "kind": kind,
                    "metadata": {
                        "name": f"{kind.lower()}-1",
                        "namespace": kwargs.get("namespace"),
                        "managedFields": [{"manager": "x"}],
                        "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "{}"},
                    },
                }
            ],
        }

    def get(self, api_version: str, kind: str, name: str, **kwargs: Any) -> dict[str, Any]:
        self._record("get", api_version, kind, name, **kwargs)
        # A test can seed self.objects[(kind, ns)] to return a specific object...
        key = (kind, kwargs.get("namespace"))
        if key in self.objects and self.objects[key]["metadata"]["name"] == name:
            return self.objects[key]
        # ...otherwise return a minimal stub.
        return {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": {"name": name, "managedFields": []},
        }

    def apply(self, manifest: dict[str, Any]) -> dict[str, Any]:
        self._record("apply", manifest)
        # Echo the manifest back with a server-assigned uid, like a real apply.
        return {**manifest, "metadata": {**manifest.get("metadata", {}), "uid": "u1"}}

    def delete(self, api_version: str, kind: str, name: str, **kwargs: Any) -> dict[str, Any]:
        self._record("delete", api_version, kind, name, **kwargs)
        return {"kind": "Status", "status": "Success", "details": {"name": name}}

    def patch(
        self, api_version: str, kind: str, name: str, namespace: str | None, merge_patch: dict
    ) -> dict[str, Any]:
        self._record("patch", api_version, kind, name, namespace, merge_patch)
        return {"apiVersion": api_version, "kind": kind, "spec": merge_patch.get("spec", {})}

    def instantiate(
        self, api_version: str, kind: str, subresource: str, name: str, namespace: str | None, body
    ) -> dict[str, Any]:
        self._record("instantiate", api_version, kind, subresource, name, namespace, body)
        return {"kind": "Build", "metadata": {"name": f"{name}-1"}, "status": {"phase": "New"}}

    def pod_logs(self, name: str, namespace: str, **kwargs: Any) -> str:
        self._record("pod_logs", name, namespace, **kwargs)
        return "log line 1\nlog line 2\n"

    def server_version(self) -> dict[str, Any]:
        self._record("server_version")
        return {"gitVersion": "v1.30.0"}

    def probe(self, timeout: float = 5.0) -> tuple[bool, bool | None, str | None]:
        self._record("probe", timeout)
        return True, self.is_openshift, None


def api_exception(status: int, message: str = "boom") -> ApiException:
    """A kubernetes ApiException shaped like a real one (status + Status JSON body),
    for testing errors.tool_error's status-code mapping."""
    exc = ApiException(status=status, reason=message)
    exc.body = f'{{"message": "{message}"}}'  # k8s Status object - _api_message() parses this
    return exc
