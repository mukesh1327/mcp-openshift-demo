from __future__ import annotations

from openshift_mcp.sanitize import sanitize


def test_strips_managed_fields_and_noise_annotations() -> None:
    obj = {
        "metadata": {
            "name": "x",
            "managedFields": [{"manager": "kubectl"}],
            "annotations": {
                "kubectl.kubernetes.io/last-applied-configuration": "{}",
                "keep-me": "yes",
            },
        }
    }
    out = sanitize(obj)
    assert "managedFields" not in out["metadata"]
    assert out["metadata"]["annotations"] == {"keep-me": "yes"}


def test_drops_empty_annotations_dict() -> None:
    obj = {"metadata": {"annotations": {"kapp.k14s.io/original": "x"}}}
    assert "annotations" not in sanitize(obj)["metadata"]


def test_recurses_into_list_items() -> None:
    payload = {
        "kind": "PodList",
        "items": [
            {"metadata": {"name": "a", "managedFields": [1]}},
            {"metadata": {"name": "b", "managedFields": [2]}},
        ],
    }
    out = sanitize(payload)
    assert all("managedFields" not in i["metadata"] for i in out["items"])


def test_passthrough_non_dict() -> None:
    assert sanitize("plain text") == "plain text"
    assert sanitize([1, 2]) == [1, 2]
