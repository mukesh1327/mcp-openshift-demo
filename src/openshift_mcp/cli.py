"""Console-script entry point."""

from __future__ import annotations

import sys

from .config import load
from .server import run


def main(argv: list[str] | None = None) -> int:
    try:
        cfg = load(argv)
    except (ValueError, OSError) as exc:
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 2

    try:
        run(cfg)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"openshift-mcp-server: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
