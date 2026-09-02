# mcp-openshift-server

An [MCP](https://modelcontextprotocol.io) server, written in Go, that exposes OpenShift/Kubernetes cluster operations as tools for MCP clients (Claude Desktop, Claude Code, and others).

It provides **read-only observability** (namespaces/projects, pods, deployments, deploymentconfigs, replicasets, services, routes, builds, buildconfigs, imagestreams, events, pod logs) plus a small set of **safe write operations** (scale a deployment/deploymentconfig, restart a rollout, trigger a build). It deliberately does **not** expose arbitrary create/delete, namespace deletion, pod exec, or port-forwarding.

## How it works

- Built on the official [`modelcontextprotocol/go-sdk`](https://github.com/modelcontextprotocol/go-sdk).
- Talks to the cluster via [`k8s.io/client-go`](https://github.com/kubernetes/client-go) (core Kubernetes resources) and [`github.com/openshift/client-go`](https://github.com/openshift/client-go) (OpenShift-only resources: Route, Project, DeploymentConfig, Build, BuildConfig, ImageStream).
- Detects whether the target cluster is OpenShift via API discovery; OpenShift-only tools simply aren't registered on vanilla Kubernetes.
- Supports two transports, selected at startup: **stdio** (for local MCP clients) and **streamable HTTP** (for remote/in-cluster deployment).

## Authentication

The server never implements its own authorization layer — whatever credentials it runs with are the credentials it uses, and RBAC on those credentials is the only access boundary. Two modes, tried in this order:

1. **In-cluster ServiceAccount** (`rest.InClusterConfig`) — used automatically when running as a Pod inside Kubernetes/OpenShift. Grant it exactly the verbs it needs via the Role in [`deploy/role.yaml`](deploy/role.yaml).
2. **kubeconfig** — used otherwise, with standard `kubectl`/`oc` precedence: an explicit `-kubeconfig` flag/`KUBECONFIG` env var, falling back to `~/.kube/config`. This means an existing `oc login` session is picked up automatically for local development.

## Building

```sh
make build          # -> bin/mcp-openshift-server
make test
make lint           # requires golangci-lint
```

## Running

### stdio (local MCP client)

```sh
make run
# or directly:
./bin/mcp-openshift-server -transport=stdio
```

Example Claude Desktop / Claude Code MCP config:

```json
{
  "mcpServers": {
    "openshift": {
      "command": "/path/to/bin/mcp-openshift-server",
      "args": ["-transport=stdio"]
    }
  }
}
```

### streamable HTTP (remote/in-cluster)

```sh
make run-http
# or directly:
./bin/mcp-openshift-server -transport=http -http-addr=:8080
```

The MCP endpoint is served at `/`. `/healthz` is a static liveness check; `/readyz` performs a cheap cluster discovery call, suitable for a Kubernetes readiness probe.

### Configuration

Every option is a flag with an environment-variable fallback (flags win):

| Flag | Env var | Default | Purpose |
|---|---|---|---|
| `-transport` | `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `-http-addr` | `MCP_HTTP_ADDR` | `:8080` | listen address for `-transport=http` |
| `-kubeconfig` | `KUBECONFIG` | *(unset)* | explicit kubeconfig path |
| `-request-timeout` | `MCP_REQUEST_TIMEOUT` | `30s` | timeout applied to every cluster API call |
| `-list-limit` | `MCP_LIST_LIMIT` | `500` | max items returned by list tools |
| `-logs-max-tail-lines` | `MCP_LOGS_MAX_TAIL_LINES` | `5000` | max `tail_lines` accepted by `pods_logs` |
| `-read-only` | `MCP_READ_ONLY` | `false` | disable every write tool (they won't even appear in `tools/list`) |
| `-log-level` | `MCP_LOG_LEVEL` | `info` | `debug`, `info`, `warn`, `error` |
| `-log-format` | `MCP_LOG_FORMAT` | `json` | `json` or `text` |

## Tools

Every namespaced tool requires an explicit `namespace` — none default to "all namespaces". OpenShift-only tools are marked *(OS)* and are only registered when the server detects an OpenShift cluster.

| Tool | Kind | Description |
|---|---|---|
| `namespaces_list` / `namespaces_get` | read | List/get Kubernetes namespaces (cluster-scoped) |
| `projects_list` / `projects_get` *(OS)* | read | List/get OpenShift Projects (respects project visibility) |
| `pods_list` / `pods_get` | read | List/get pods, with label/field selectors |
| `pods_logs` | read | Fetch recent container logs (tail-capped) |
| `deployments_list` / `deployments_get` | read | List/get Deployments |
| `deployments_scale` | **write** | Scale a Deployment via the `/scale` subresource |
| `deployments_restart` | **write** | Rolling restart (patches the pod template's restart annotation, like `kubectl rollout restart`) |
| `deploymentconfigs_list` / `deploymentconfigs_get` *(OS)* | read | List/get DeploymentConfigs |
| `deploymentconfigs_scale` *(OS)* | **write** | Scale a DeploymentConfig via the `/scale` subresource |
| `deploymentconfigs_restart` *(OS)* | **write** | New rollout from latest state (`Instantiate`, like `oc rollout latest`) |
| `replicasets_list` / `replicasets_get` | read | List/get ReplicaSets |
| `services_list` / `services_get` | read | List/get Services |
| `routes_list` / `routes_get` *(OS)* | read | List/get Routes |
| `builds_list` / `builds_get` *(OS)* | read | List/get Builds |
| `buildconfigs_list` / `buildconfigs_get` *(OS)* | read | List/get BuildConfigs |
| `buildconfigs_trigger` *(OS)* | **write** | Trigger a new Build (`Instantiate`, like `oc start-build`) |
| `imagestreams_list` / `imagestreams_get` *(OS)* | read | List/get ImageStreams |
| `events_list` | read | Recent events in a namespace, most recent first |

There are no `*_describe` tools: `*_get` returns the full structured object as JSON, which is more useful to an LLM client than `kubectl describe`'s text format.

## Deploying to OpenShift/Kubernetes

Manifests are in [`deploy/`](deploy/):

```sh
oc new-project mcp-openshift-server   # or: kubectl create namespace mcp-openshift-server
oc apply -f deploy/serviceaccount.yaml
oc apply -f deploy/role.yaml
oc apply -f deploy/rolebinding.yaml
oc apply -f deploy/deployment.yaml   # set the image first
oc apply -f deploy/service.yaml
oc apply -f deploy/route.yaml        # optional, for external access
```

`deploy/role.yaml` grants exactly the verbs the tools above use, scoped to the namespace you bind it in. `deploy/clusterrole-projects.yaml` + `deploy/clusterrolebinding.yaml` are optional and separate — apply them only if you want `namespaces_list`/`projects_list` to see across the whole cluster.

## Development notes

- `internal/config` — flag/env parsing, no cluster dependency.
- `internal/k8sclient` — client construction (in-cluster → kubeconfig fallback) and OpenShift capability detection.
- `internal/mcptools` — one file per resource domain; `register.go` wires it all together, gating write tools on `-read-only` and OpenShift-only tools on cluster capability detection.
- `internal/server` — stdio and streamable-HTTP transport wiring, including graceful shutdown.

Tests use `k8s.io/client-go/kubernetes/fake` and the OpenShift clientsets' generated `fake` packages — no live cluster required. Write-tool tests assert on the fake clientset's action tracker that exactly the expected verb/subresource fired, as a regression guard against scope creep into destructive operations.
