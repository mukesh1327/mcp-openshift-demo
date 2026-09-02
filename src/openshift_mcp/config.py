"""Runtime configuration, resolved from (lowest to highest precedence):
defaults < TOML file (--config) < environment (MCP_*) < CLI flags.
"""

from __future__ import annotations

import argparse
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import Any

DEFAULT_TOOLSETS = ("core", "config", "openshift")
KNOWN_TOOLSETS = ("core", "config", "openshift")

_ENV_PREFIX = "MCP_"


@dataclass(frozen=True, slots=True)
class Config:
    # transport
    transport: str = "stdio"  # "stdio" | "http"
    host: str = "127.0.0.1"
    port: int = 8080

    # cluster access
    kubeconfig: str | None = None
    context: str | None = None  # default context; tools may override per call
    in_cluster: bool = False  # force in-cluster credentials

    # safety
    read_only: bool = False  # only list/get/log tools are registered
    disable_destructive: bool = True  # delete tools are not registered

    # tool surface
    toolsets: tuple[str, ...] = DEFAULT_TOOLSETS

    # limits
    list_limit: int = 200
    log_max_lines: int = 500
    request_timeout: int = 30

    # output / logging
    list_output: str = "json"  # "json" | "yaml"
    log_level: str = "INFO"

    def validate(self) -> None:
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"invalid transport {self.transport!r}: must be 'stdio' or 'http'")
        if self.transport == "http" and not self.host:
            raise ValueError("host must not be empty for the http transport")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port out of range: {self.port}")
        for value, name in (
            (self.list_limit, "list_limit"),
            (self.log_max_lines, "log_max_lines"),
            (self.request_timeout, "request_timeout"),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        unknown = set(self.toolsets) - set(KNOWN_TOOLSETS)
        if unknown:
            raise ValueError(
                f"unknown toolset(s): {', '.join(sorted(unknown))}; "
                f"known: {', '.join(KNOWN_TOOLSETS)}"
            )
        if not self.toolsets:
            raise ValueError("at least one toolset must be enabled")
        if self.list_output not in ("json", "yaml"):
            raise ValueError(f"invalid list_output {self.list_output!r}: must be 'json' or 'yaml'")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"invalid log_level {self.log_level!r}")


_FIELD_NAMES = {f.name for f in fields(Config)}


def _coerce(name: str, raw: Any) -> Any:
    """Coerce a string (from env/TOML) to the dataclass field's type."""
    if name in ("port", "list_limit", "log_max_lines", "request_timeout"):
        return int(raw)
    if name in ("read_only", "disable_destructive", "in_cluster"):
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if name == "toolsets":
        if isinstance(raw, str):
            return tuple(t.strip() for t in raw.split(",") if t.strip())
        return tuple(raw)
    if name == "log_level":
        return str(raw).upper()
    return raw


def _from_toml(path: str) -> dict[str, Any]:
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    # allow either a flat table or a [server] table
    if "server" in data and isinstance(data["server"], Mapping):
        data = data["server"]
    return {
        k.replace("-", "_"): _coerce(k.replace("-", "_"), v)
        for k, v in data.items()
        if k.replace("-", "_") in _FIELD_NAMES
    }


def _from_env(environ: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        name = key[len(_ENV_PREFIX) :].lower()
        if name in _FIELD_NAMES:
            out[name] = _coerce(name, value)
    # honour the conventional KUBECONFIG too
    if "KUBECONFIG" in environ and "kubeconfig" not in out:
        out["kubeconfig"] = environ["KUBECONFIG"]
    return out


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openshift-mcp-server",
        description="MCP server exposing OpenShift/Kubernetes cluster operations as tools.",
    )
    # argparse.SUPPRESS defaults: only keys the user actually passed appear in the namespace
    p.add_argument("--config", help="path to a TOML config file", default=argparse.SUPPRESS)
    p.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=argparse.SUPPRESS,
        help="MCP transport (default: stdio)",
    )
    p.add_argument("--host", default=argparse.SUPPRESS, help="listen host for --transport=http")
    p.add_argument(
        "--port", type=int, default=argparse.SUPPRESS, help="listen port for --transport=http"
    )
    p.add_argument("--kubeconfig", default=argparse.SUPPRESS, help="path to kubeconfig")
    p.add_argument("--context", default=argparse.SUPPRESS, help="default kubeconfig context")
    p.add_argument(
        "--in-cluster",
        action="store_true",
        default=argparse.SUPPRESS,
        help="force in-cluster ServiceAccount credentials",
    )
    p.add_argument(
        "--read-only",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="register only read tools (default: off)",
    )
    p.add_argument(
        "--disable-destructive",
        action=argparse.BooleanOptionalAction,
        default=argparse.SUPPRESS,
        help="do not register delete tools (default: on)",
    )
    p.add_argument(
        "--toolsets",
        default=argparse.SUPPRESS,
        help=f"comma-separated toolsets (default: {','.join(DEFAULT_TOOLSETS)}; "
        f"known: {','.join(KNOWN_TOOLSETS)})",
    )
    p.add_argument(
        "--list-limit", type=int, default=argparse.SUPPRESS, help="max items per list tool"
    )
    p.add_argument("--log-max-lines", type=int, default=argparse.SUPPRESS, help="max pod-log lines")
    p.add_argument(
        "--request-timeout", type=int, default=argparse.SUPPRESS, help="per-call timeout (s)"
    )
    p.add_argument(
        "--list-output",
        choices=("json", "yaml"),
        default=argparse.SUPPRESS,
        help="serialization of tool results (default: json)",
    )
    p.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default=argparse.SUPPRESS,
    )
    return p


def load(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Resolve a Config from CLI args and the environment."""
    environ = os.environ if environ is None else environ
    ns = vars(_build_parser().parse_args(argv))

    values: dict[str, Any] = {}
    config_path = ns.pop("config", None)
    if config_path:
        values.update(_from_toml(config_path))
    values.update(_from_env(environ))
    values.update({k: v for k, v in ns.items() if k in _FIELD_NAMES})

    if "toolsets" in values and isinstance(values["toolsets"], str):
        values["toolsets"] = _coerce("toolsets", values["toolsets"])

    cfg = Config(**values)
    cfg.validate()
    return cfg
