package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

// NamespaceGetParams identifies a single namespace.
type NamespaceGetParams struct {
	Name string `json:"name" jsonschema:"name of the namespace to fetch"`
}

func registerNamespaceTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "namespaces_list",
		Description: "Read-only. List all Kubernetes namespaces visible to the server's credentials. Cluster-scoped (not limited to one namespace).",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("namespaces_list", func(ctx context.Context, _ *mcp.CallToolRequest, _ EmptyParams) (*mcp.CallToolResult, any, error) {
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Core.CoreV1().Namespaces().List(ctx, metav1.ListOptions{Limit: clampLimit(0, cfg)})
		if err != nil {
			return nil, nil, wrapAPIError("listing namespaces", err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "namespaces_get",
		Description: "Read-only. Get a single Kubernetes namespace by name, including its status and labels.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("namespaces_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceGetParams) (*mcp.CallToolResult, any, error) {
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		ns, err := clients.Core.CoreV1().Namespaces().Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting namespace "+in.Name, err)
		}
		return nil, ns, nil
	}))
}
