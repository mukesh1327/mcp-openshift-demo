package mcptools

import (
	"context"
	"sort"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

type EventsListParams struct {
	Namespace     string `json:"namespace" jsonschema:"namespace to list events in"`
	FieldSelector string `json:"field_selector,omitempty" jsonschema:"optional field selector, e.g. involvedObject.name=my-pod"`
	Limit         int64  `json:"limit,omitempty" jsonschema:"optional maximum number of events to return, most recent first"`
}

func registerEventTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "events_list",
		Description: "Read-only. List recent Kubernetes events in a namespace, most recent first, optionally filtered by field selector (e.g. to find events for one object).",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("events_list", func(ctx context.Context, _ *mcp.CallToolRequest, in EventsListParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Core.CoreV1().Events(in.Namespace).List(ctx, metav1.ListOptions{
			FieldSelector: in.FieldSelector,
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing events in namespace "+in.Namespace, err)
		}

		sort.Slice(list.Items, func(i, j int) bool {
			return eventTimestamp(list.Items[i]).After(eventTimestamp(list.Items[j]))
		})

		limit := clampLimit(in.Limit, cfg)
		if int64(len(list.Items)) > limit {
			list.Items = list.Items[:limit]
		}
		return nil, list, nil
	}))
}

func eventTimestamp(e corev1.Event) time.Time {
	if !e.LastTimestamp.IsZero() {
		return e.LastTimestamp.Time
	}
	if !e.EventTime.IsZero() {
		return e.EventTime.Time
	}
	return e.CreationTimestamp.Time
}
