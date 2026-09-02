"""Console-script entry point."""

from __future__ import annotations

import sys

from .config import load
from .server import run


def main(argv: list[str] | None = None) -> int:
    """Process entry point (wired up as the ``openshift-mcp-server`` script).

    Returns a shell exit code:
      2 - bad configuration (invalid flag/env/TOML, unreadable --config file)
      1 - the server crashed at runtime
      0 - clean shutdown, including Ctrl-C
    """
    try:
        cfg = load(argv)
    except (ValueError, OSError) as exc:
        # ValueError: Config.validate() rejected a value. OSError: --config unreadable.
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 2

    try:
        run(cfg)  # blocks here serving the transport until interrupted
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
