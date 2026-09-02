package mcptools

import (
	"strings"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func TestPodsList(t *testing.T) {
	core := fake.NewSimpleClientset(
		&corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "web-1", Namespace: "demo", Labels: map[string]string{"app": "web"}}},
		&corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "worker-1", Namespace: "demo", Labels: map[string]string{"app": "worker"}}},
		&corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "other-ns-pod", Namespace: "other"}},
	)
	clients := &k8sclient.Clients{Core: core}
	cfg := config.Default()

	session := newTestSession(t, func(s *mcp.Server) { registerPodTools(s, clients, cfg) })

	var list corev1.PodList
	callTool(t, session, "pods_list", map[string]any{"namespace": "demo"}, &list)
	if len(list.Items) != 2 {
		t.Fatalf("got %d pods, want 2", len(list.Items))
	}

	var filtered corev1.PodList
	callTool(t, session, "pods_list", map[string]any{"namespace": "demo", "label_selector": "app=web"}, &filtered)
	if len(filtered.Items) != 1 || filtered.Items[0].Name != "web-1" {
		t.Fatalf("label selector filter failed, got %+v", filtered.Items)
	}
}

func TestPodsList_RequiresNamespace(t *testing.T) {
	clients := &k8sclient.Clients{Core: fake.NewSimpleClientset()}
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerPodTools(s, clients, cfg) })

	result, err := session.CallTool(t.Context(), &mcp.CallToolParams{Name: "pods_list", Arguments: map[string]any{}})
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if !result.IsError {
		t.Fatalf("expected error result when namespace is missing")
	}
}

func TestPodsGet_NotFound(t *testing.T) {
	clients := &k8sclient.Clients{Core: fake.NewSimpleClientset()}
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerPodTools(s, clients, cfg) })

	result, err := session.CallTool(t.Context(), &mcp.CallToolParams{
		Name:      "pods_get",
		Arguments: map[string]any{"namespace": "demo", "name": "missing"},
	})
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	msg := errorText(t, result)
	if !strings.Contains(msg, "getting pod") || !strings.Contains(msg, "not found") {
		t.Errorf("error message = %q, want it to mention the failed action and not-found", msg)
	}
}

func TestPodsLogs(t *testing.T) {
	core := fake.NewSimpleClientset(
		&corev1.Pod{ObjectMeta: metav1.ObjectMeta{Name: "web-1", Namespace: "demo"}},
	)
	clients := &k8sclient.Clients{Core: core}
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerPodTools(s, clients, cfg) })

	var logs string
	callTool(t, session, "pods_logs", map[string]any{"namespace": "demo", "name": "web-1"}, &logs)
	// The fake clientset returns a canned "fake logs" body; we only assert
	// the call succeeds end-to-end and returns text, not its exact content.
	if logs == "" {
		t.Errorf("expected non-empty log output from fake clientset")
	}
}
