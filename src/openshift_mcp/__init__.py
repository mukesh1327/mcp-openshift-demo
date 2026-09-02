"""MCP server exposing OpenShift/Kubernetes cluster operations as tools.

Layout:
  config.py    - CLI / env / TOML configuration
  k8s.py       - cluster client construction, multi-context manager, capability detection
  sanitize.py  - strip context-bloating fields from API objects
  errors.py    - map Kubernetes API errors to clear tool-error messages
  toolsets/    - one module per toolset (core, config, openshift); registered on demand
  server.py    - build the MCPServer and run a transport
  cli.py       - entry point
"""

__version__ = "0.1.0"
