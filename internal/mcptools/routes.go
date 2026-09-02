package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func registerRouteTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "routes_list",
		Description: "Read-only. OpenShift only. List Routes in a namespace, optionally filtered by label selector.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("routes_list", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceLabelSelectorParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Route.RouteV1().Routes(in.Namespace).List(ctx, metav1.ListOptions{
			LabelSelector: in.LabelSelector,
			Limit:         clampLimit(0, cfg),
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing routes in namespace "+in.Namespace, err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "routes_get",
		Description: "Read-only. OpenShift only. Get the full structured spec and status of a single Route, including its external host.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("routes_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		route, err := clients.Route.RouteV1().Routes(in.Namespace).Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting route "+in.Namespace+"/"+in.Name, err)
		}
		return nil, route, nil
	}))
}
