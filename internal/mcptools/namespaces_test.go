package mcptools

import (
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes/fake"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func TestNamespacesListAndGet(t *testing.T) {
	core := fake.NewSimpleClientset(
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "demo"}},
		&corev1.Namespace{ObjectMeta: metav1.ObjectMeta{Name: "kube-system"}},
	)
	clients := &k8sclient.Clients{Core: core}
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerNamespaceTools(s, clients, cfg) })

	var list corev1.NamespaceList
	callTool(t, session, "namespaces_list", map[string]any{}, &list)
	if len(list.Items) != 2 {
		t.Fatalf("got %d namespaces, want 2", len(list.Items))
	}

	var ns corev1.Namespace
	callTool(t, session, "namespaces_get", map[string]any{"name": "demo"}, &ns)
	if ns.Name != "demo" {
		t.Errorf("got namespace %q, want demo", ns.Name)
	}

	result, err := session.CallTool(t.Context(), &mcp.CallToolParams{Name: "namespaces_get", Arguments: map[string]any{"name": "nope"}})
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if !result.IsError {
		t.Fatalf("expected error for missing namespace")
	}
}
