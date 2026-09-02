package mcptools

import (
	"log/slog"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

// RegisterAll registers every tool the server exposes.
//
// Write tools are skipped entirely when cfg.ReadOnly is true — they never
// appear in tools/list, rather than merely rejecting calls at runtime.
// OpenShift-only tools (routes, projects, deploymentconfigs, builds,
// buildconfigs, imagestreams) are skipped when isOpenShift is false, since
// those API groups don't exist on vanilla Kubernetes.
func RegisterAll(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config, isOpenShift bool, log *slog.Logger) {
	SetLogger(log)

	registerNamespaceTools(server, clients, cfg)
	registerPodTools(server, clients, cfg)
	registerDeploymentTools(server, clients, cfg)
	registerReplicaSetTools(server, clients, cfg)
	registerServiceTools(server, clients, cfg)
	registerEventTools(server, clients, cfg)

	if isOpenShift {
		registerProjectTools(server, clients, cfg)
		registerDeploymentConfigTools(server, clients, cfg)
		registerRouteTools(server, clients, cfg)
		registerBuildTools(server, clients, cfg)
		registerBuildConfigTools(server, clients, cfg)
		registerImageStreamTools(server, clients, cfg)
	}
}
