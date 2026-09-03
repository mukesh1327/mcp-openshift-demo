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

# Toolsets enabled when the user passes no --toolsets flag, and the full set of
# names the flag will accept. Keep both in sync with toolsets/__init__.py:KNOWN.
DEFAULT_TOOLSETS = ("core", "config", "openshift")
KNOWN_TOOLSETS = ("core", "config", "openshift")

# Every environment variable we read is MCP_<FIELD> (e.g. MCP_TRANSPORT -> transport).
_ENV_PREFIX = "MCP_"


@dataclass(frozen=True, slots=True)
class Config:
    """The server's fully-resolved runtime settings.

    Immutable so it can be shared freely between threads (tool calls run
    concurrently); every attribute below is also a CLI flag and an ``MCP_*``
    env var. Build one with ``load()`` - never instantiate directly outside tests.
    """

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
        """Reject any out-of-range or unknown value with a ``ValueError``.

        Called once after the merged Config is built (see ``load()``); the
        ``ValueError`` propagates to ``cli.main`` which exits 2 with a readable
        message, instead of the bad value failing deep inside a later tool call.
        """
        # transport: the only two the MCP package's server.run() understands here
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"invalid transport {self.transport!r}: must be 'stdio' or 'http'")
        # host/port only matter for http, but validate them whenever http is selected
        if self.transport == "http" and not self.host:
            raise ValueError("host must not be empty for the http transport")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"port out of range: {self.port}")
        # every limit is later used as a positive cap / timeout - 0 or negative is nonsense
        for value, name in (
            (self.list_limit, "list_limit"),
            (self.log_max_lines, "log_max_lines"),
            (self.request_timeout, "request_timeout"),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        # catch a typo'd toolset name now rather than silently registering nothing
        unknown = set(self.toolsets) - set(KNOWN_TOOLSETS)
        if unknown:
            raise ValueError(
                f"unknown toolset(s): {', '.join(sorted(unknown))}; "
                f"known: {', '.join(KNOWN_TOOLSETS)}"
            )
        if not self.toolsets:  # e.g. --toolsets "" - the server would expose no tools
            raise ValueError("at least one toolset must be enabled")
        if self.list_output not in ("json", "yaml"):
            raise ValueError(f"invalid list_output {self.list_output!r}: must be 'json' or 'yaml'")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"invalid log_level {self.log_level!r}")


# Set of valid Config attribute names - used to filter env/TOML/CLI keys before
# they reach Config(**values), so an unrecognised key is dropped, not an error.
_FIELD_NAMES = {f.name for f in fields(Config)}


def _coerce(name: str, raw: Any) -> Any:
    """Coerce a raw value to the dataclass field's type.

    Env vars arrive as strings and TOML values as their TOML type, but `Config`
    wants ``int`` / ``bool`` / ``tuple[str, ...]``. CLI flags are already typed by
    argparse, so this is a no-op for them.
    """
    # integer fields: int("30") from env, int(30) from TOML - both fine
    if name in ("port", "list_limit", "log_max_lines", "request_timeout"):
        return int(raw)
    # boolean fields: accept the usual truthy spellings from a string env var
    if name in ("read_only", "disable_destructive", "in_cluster"):
        if isinstance(raw, bool):  # TOML booleans / argparse flags pass straight through
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if name == "toolsets":
        # accept both "core,config" (env/CLI) and ["core", "config"] (TOML array)
        if isinstance(raw, str):
            return tuple(t.strip() for t in raw.split(",") if t.strip())
        return tuple(raw)
    if name == "log_level":
        return str(raw).upper()
    return raw


def _from_toml(path: str) -> dict[str, Any]:
    """Read a --config TOML file into a dict of Config kwargs (unknown keys dropped)."""
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    # Accept either a flat table (transport = "http") or a [server] table.
    if "server" in data and isinstance(data["server"], Mapping):
        data = data["server"]
    # TOML keys may use dashes (list-limit); Config fields use underscores.
    return {
        k.replace("-", "_"): _coerce(k.replace("-", "_"), v)
        for k, v in data.items()
        if k.replace("-", "_") in _FIELD_NAMES
    }


def _from_env(environ: Mapping[str, str]) -> dict[str, Any]:
    """Pull MCP_<FIELD> variables out of the environment into Config kwargs."""
    out: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(_ENV_PREFIX):
            continue
        name = key[len(_ENV_PREFIX) :].lower()  # MCP_LOG_LEVEL -> "log_level"
        if name in _FIELD_NAMES:
            out[name] = _coerce(name, value)
    # Also honour the conventional KUBECONFIG (no MCP_ prefix) unless MCP_KUBECONFIG won.
    if "KUBECONFIG" in environ and "kubeconfig" not in out:
        out["kubeconfig"] = environ["KUBECONFIG"]
    return out


def _build_parser() -> argparse.ArgumentParser:
    """Construct the CLI parser (one argument per Config field, plus ``--config``).

    Every argument uses ``default=argparse.SUPPRESS`` so a flag the user did NOT
    pass is simply absent from the parsed namespace. That is what lets ``load()``
    layer CLI over env over TOML: a missing flag never overwrites a lower layer
    with a default value.
    """
    p = argparse.ArgumentParser(
        prog="openshift-mcp-server",
        description="MCP server exposing OpenShift/Kubernetes cluster operations as tools.",
    )
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
    """Resolve a Config by merging, lowest precedence first:
    dataclass defaults < TOML (--config) < environment (MCP_*) < CLI flags.
    ``argv``/``environ`` are injectable so tests don't touch the real process.
    """
    environ = os.environ if environ is None else environ
    # ns holds ONLY the flags actually passed (default=SUPPRESS on every argument)
    ns = vars(_build_parser().parse_args(argv))

    # Start empty and .update() each layer in order; the last writer wins.
    values: dict[str, Any] = {}
    config_path = ns.pop("config", None)  # --config is not a Config field itself
    if config_path:
        values.update(_from_toml(config_path))
    values.update(_from_env(environ))
    # Only real Config fields from the namespace (drops anything argparse-only).
    values.update({k: v for k, v in ns.items() if k in _FIELD_NAMES})

    # --toolsets from argparse is still the raw "a,b,c" string at this point.
    if "toolsets" in values and isinstance(values["toolsets"], str):
        values["toolsets"] = _coerce("toolsets", values["toolsets"])

    cfg = Config(**values)
    cfg.validate()  # raises ValueError -> cli.main() turns it into exit code 2
    return cfg
