package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	osappsv1 "github.com/openshift/api/apps/v1"
	extensionsv1beta1 "k8s.io/api/extensions/v1beta1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func registerDeploymentConfigTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "deploymentconfigs_list",
		Description: "Read-only. OpenShift only. List DeploymentConfigs in a namespace, optionally filtered by label selector.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("deploymentconfigs_list", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceLabelSelectorParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Apps.AppsV1().DeploymentConfigs(in.Namespace).List(ctx, metav1.ListOptions{
			LabelSelector: in.LabelSelector,
			Limit:         clampLimit(0, cfg),
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing deploymentconfigs in namespace "+in.Namespace, err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deploymentconfigs_get",
		Description: "Read-only. OpenShift only. Get the full structured spec and status of a single DeploymentConfig.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("deploymentconfigs_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		dc, err := clients.Apps.AppsV1().DeploymentConfigs(in.Namespace).Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting deploymentconfig "+in.Namespace+"/"+in.Name, err)
		}
		return nil, dc, nil
	}))

	if cfg.ReadOnly {
		return
	}

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deploymentconfigs_scale",
		Description: "Safe write. OpenShift only. Scale a DeploymentConfig to an explicit replica count via the /scale subresource. Does not create or delete any other resource.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: ptrBool(false), IdempotentHint: true},
	}, wrap("deploymentconfigs_scale", func(ctx context.Context, _ *mcp.CallToolRequest, in ScaleParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		if err := validateReplicas(in.Replicas); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		scale := &extensionsv1beta1.Scale{
			ObjectMeta: metav1.ObjectMeta{Name: in.Name, Namespace: in.Namespace},
			Spec:       extensionsv1beta1.ScaleSpec{Replicas: in.Replicas},
		}
		result, err := clients.Apps.AppsV1().DeploymentConfigs(in.Namespace).UpdateScale(ctx, in.Name, scale, metav1.UpdateOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("scaling deploymentconfig "+in.Namespace+"/"+in.Name, err)
		}
		return nil, result, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deploymentconfigs_restart",
		Description: "Safe write. OpenShift only. Trigger a new rollout of a DeploymentConfig from its latest state (equivalent to `oc rollout latest`). Does not change replica count or any other spec field.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: ptrBool(false), IdempotentHint: false},
	}, wrap("deploymentconfigs_restart", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		req := &osappsv1.DeploymentRequest{
			Name:   in.Name,
			Latest: true,
			Force:  true,
		}
		dc, err := clients.Apps.AppsV1().DeploymentConfigs(in.Namespace).Instantiate(ctx, in.Name, req, metav1.CreateOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("restarting deploymentconfig "+in.Namespace+"/"+in.Name, err)
		}
		return nil, dc, nil
	}))
}
