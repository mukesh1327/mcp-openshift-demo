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
    # Phase 1 - build config. Failures here are the user's mistake, not a bug.
    try:
        cfg = load(argv)
    except (ValueError, OSError) as exc:
        # ValueError: Config.validate() rejected a value. OSError: --config unreadable.
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 2

    # Phase 2 - run the server. run() blocks until the transport closes.
    try:
        run(cfg)
    except KeyboardInterrupt:
        return 0  # Ctrl-C is a normal way to stop a stdio server
    except Exception as exc:
        # Anything else escaping run() is a genuine crash; print it and fail.
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # `python src/openshift_mcp/cli.py` - map the int return to the process exit code.
    raise SystemExit(main())
