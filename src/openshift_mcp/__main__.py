# Enables `python -m openshift_mcp ...` as an alias for the console script.
from .cli import main

raise SystemExit(main())
