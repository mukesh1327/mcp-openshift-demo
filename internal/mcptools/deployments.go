package mcptools

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	autoscalingv1 "k8s.io/api/autoscaling/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

const maxScaleReplicas = 100

// restartedAtAnnotation is the same annotation `kubectl rollout restart`
// writes; kubelet/controller-manager treat any change to the pod template
// (including this annotation) as a trigger for a rolling restart.
const restartedAtAnnotation = "kubectl.kubernetes.io/restartedAt"

type NamespaceLabelSelectorParams struct {
	Namespace     string `json:"namespace" jsonschema:"namespace to list in"`
	LabelSelector string `json:"label_selector,omitempty" jsonschema:"optional Kubernetes label selector"`
}

type NamespaceNameParams struct {
	Namespace string `json:"namespace" jsonschema:"namespace containing the resource"`
	Name      string `json:"name" jsonschema:"resource name"`
}

type ScaleParams struct {
	Namespace string `json:"namespace" jsonschema:"namespace containing the resource"`
	Name      string `json:"name" jsonschema:"resource name"`
	Replicas  int32  `json:"replicas" jsonschema:"desired replica count (0 or greater, capped at a sane maximum)"`
}

func validateReplicas(replicas int32) error {
	if replicas < 0 {
		return fmt.Errorf("replicas must be 0 or greater, got %d", replicas)
	}
	if replicas > maxScaleReplicas {
		return fmt.Errorf("replicas must be %d or fewer (safety cap); use the cluster console/CLI directly for larger scale operations", maxScaleReplicas)
	}
	return nil
}

func registerDeploymentTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "deployments_list",
		Description: "Read-only. List Deployments in a namespace, optionally filtered by label selector.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("deployments_list", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceLabelSelectorParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Core.AppsV1().Deployments(in.Namespace).List(ctx, metav1.ListOptions{
			LabelSelector: in.LabelSelector,
			Limit:         clampLimit(0, cfg),
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing deployments in namespace "+in.Namespace, err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deployments_get",
		Description: "Read-only. Get the full structured spec and status of a single Deployment.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("deployments_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		dep, err := clients.Core.AppsV1().Deployments(in.Namespace).Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting deployment "+in.Namespace+"/"+in.Name, err)
		}
		return nil, dep, nil
	}))

	if cfg.ReadOnly {
		return
	}

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deployments_scale",
		Description: "Safe write. Scale a Deployment to an explicit replica count via the /scale subresource. Does not create or delete any other resource.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: ptrBool(false), IdempotentHint: true},
	}, wrap("deployments_scale", func(ctx context.Context, _ *mcp.CallToolRequest, in ScaleParams) (*mcp.CallToolResult, any, error) {
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

		scale := &autoscalingv1.Scale{
			ObjectMeta: metav1.ObjectMeta{Name: in.Name, Namespace: in.Namespace},
			Spec:       autoscalingv1.ScaleSpec{Replicas: in.Replicas},
		}
		result, err := clients.Core.AppsV1().Deployments(in.Namespace).UpdateScale(ctx, in.Name, scale, metav1.UpdateOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("scaling deployment "+in.Namespace+"/"+in.Name, err)
		}
		return nil, result, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "deployments_restart",
		Description: "Safe write. Trigger a rolling restart of a Deployment (equivalent to `kubectl rollout restart`), by updating the pod template's restart annotation. Does not change replica count or any other spec field.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: ptrBool(false), IdempotentHint: false},
	}, wrap("deployments_restart", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		patch, err := restartPatch()
		if err != nil {
			return nil, nil, fmt.Errorf("building restart patch: %w", err)
		}
		dep, err := clients.Core.AppsV1().Deployments(in.Namespace).Patch(ctx, in.Name, types.StrategicMergePatchType, patch, metav1.PatchOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("restarting deployment "+in.Namespace+"/"+in.Name, err)
		}
		return nil, dep, nil
	}))
}

func restartPatch() ([]byte, error) {
	patch := map[string]any{
		"spec": map[string]any{
			"template": map[string]any{
				"metadata": map[string]any{
					"annotations": map[string]any{
						restartedAtAnnotation: time.Now().UTC().Format(time.RFC3339),
					},
				},
			},
		},
	}
	return json.Marshal(patch)
}

func ptrBool(b bool) *bool { return &b }
