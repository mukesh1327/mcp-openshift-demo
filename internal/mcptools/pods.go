package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

type PodsListParams struct {
	Namespace     string `json:"namespace" jsonschema:"namespace to list pods in"`
	LabelSelector string `json:"label_selector,omitempty" jsonschema:"optional Kubernetes label selector, e.g. app=frontend"`
	FieldSelector string `json:"field_selector,omitempty" jsonschema:"optional Kubernetes field selector, e.g. status.phase=Running"`
	Limit         int64  `json:"limit,omitempty" jsonschema:"optional maximum number of pods to return"`
}

type PodGetParams struct {
	Namespace string `json:"namespace" jsonschema:"namespace containing the pod"`
	Name      string `json:"name" jsonschema:"pod name"`
}

type PodLogsParams struct {
	Namespace    string `json:"namespace" jsonschema:"namespace containing the pod"`
	Name         string `json:"name" jsonschema:"pod name"`
	Container    string `json:"container,omitempty" jsonschema:"optional container name; required if the pod has more than one container"`
	TailLines    int64  `json:"tail_lines,omitempty" jsonschema:"optional number of lines to return from the end of the log (default and hard cap enforced server-side)"`
	Previous     bool   `json:"previous,omitempty" jsonschema:"optional: fetch logs from the previous terminated container instance instead of the current one"`
	SinceSeconds int64  `json:"since_seconds,omitempty" jsonschema:"optional: only return logs newer than this many seconds"`
}

func registerPodTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "pods_list",
		Description: "Read-only. List pods in a namespace, optionally filtered by label or field selector.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("pods_list", func(ctx context.Context, _ *mcp.CallToolRequest, in PodsListParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Core.CoreV1().Pods(in.Namespace).List(ctx, metav1.ListOptions{
			LabelSelector: in.LabelSelector,
			FieldSelector: in.FieldSelector,
			Limit:         clampLimit(in.Limit, cfg),
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing pods in namespace "+in.Namespace, err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "pods_get",
		Description: "Read-only. Get the full structured spec and status of a single pod.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("pods_get", func(ctx context.Context, _ *mcp.CallToolRequest, in PodGetParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		pod, err := clients.Core.CoreV1().Pods(in.Namespace).Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting pod "+in.Namespace+"/"+in.Name, err)
		}
		return nil, pod, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "pods_logs",
		Description: "Read-only. Fetch recent log output from a pod's container. Output is truncated to a server-enforced maximum number of lines.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("pods_logs", func(ctx context.Context, _ *mcp.CallToolRequest, in PodLogsParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		tail := clampTailLines(in.TailLines, cfg)
		opts := &corev1.PodLogOptions{
			Container: in.Container,
			Previous:  in.Previous,
			TailLines: &tail,
		}
		if in.SinceSeconds > 0 {
			opts.SinceSeconds = &in.SinceSeconds
		}

		raw, err := clients.Core.CoreV1().Pods(in.Namespace).GetLogs(in.Name, opts).DoRaw(ctx)
		if err != nil {
			return nil, nil, wrapAPIError("getting logs for pod "+in.Namespace+"/"+in.Name, err)
		}
		return nil, string(raw), nil
	}))
}
