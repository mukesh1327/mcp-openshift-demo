package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func registerProjectTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "projects_list",
		Description: "Read-only. OpenShift only. List OpenShift Projects visible to the server's credentials (respects project visibility, unlike namespaces_list). Cluster-scoped.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("projects_list", func(ctx context.Context, _ *mcp.CallToolRequest, _ EmptyParams) (*mcp.CallToolResult, any, error) {
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Project.ProjectV1().Projects().List(ctx, metav1.ListOptions{Limit: clampLimit(0, cfg)})
		if err != nil {
			return nil, nil, wrapAPIError("listing projects", err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "projects_get",
		Description: "Read-only. OpenShift only. Get a single OpenShift Project by name.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("projects_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceGetParams) (*mcp.CallToolResult, any, error) {
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		proj, err := clients.Project.ProjectV1().Projects().Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting project "+in.Name, err)
		}
		return nil, proj, nil
	}))
}
