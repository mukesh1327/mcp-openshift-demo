"""`python -m openshift_mcp ...` entry point - an alias for the `openshift-mcp-server`
console script. Both call `cli.main`; this module just adapts its int return value
into the process exit code."""

from .cli import main

raise SystemExit(main())
