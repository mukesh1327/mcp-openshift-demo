package mcptools

import (
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	buildv1 "github.com/openshift/api/build/v1"
	buildfake "github.com/openshift/client-go/build/clientset/versioned/fake"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func newBuildConfigFake(t *testing.T) (*buildfake.Clientset, *k8sclient.Clients) {
	t.Helper()
	build := buildfake.NewSimpleClientset(&buildv1.BuildConfig{
		ObjectMeta: metav1.ObjectMeta{Name: "app", Namespace: "demo"},
	})
	return build, &k8sclient.Clients{Build: build}
}

// TestBuildConfigsTrigger_CreatesExactlyOneBuild guards the write tool's
// scope: it must issue exactly one create on the buildconfigs/instantiate
// subresource, never touching the BuildConfig object itself.
func TestBuildConfigsTrigger_CreatesExactlyOneBuild(t *testing.T) {
	build, clients := newBuildConfigFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerBuildConfigTools(s, clients, cfg) })

	var result buildv1.Build
	callTool(t, session, "buildconfigs_trigger", map[string]any{
		"namespace": "demo", "name": "app", "commit_ref": "abc123",
		"env": map[string]any{"FOO": "bar"},
	}, &result)

	actions := build.Actions()
	if len(actions) != 1 {
		t.Fatalf("got %d actions, want exactly 1: %+v", len(actions), actions)
	}
	a := actions[0]
	if a.GetVerb() != "create" || a.GetResource().Resource != "buildconfigs" || a.GetSubresource() != "instantiate" {
		t.Fatalf("action = %s %s/%s, want create on buildconfigs/instantiate", a.GetVerb(), a.GetResource().Resource, a.GetSubresource())
	}
}

func TestBuildConfigTools_ReadOnlyModeHidesTrigger(t *testing.T) {
	_, clients := newBuildConfigFake(t)
	cfg := config.Default()
	cfg.ReadOnly = true
	session := newTestSession(t, func(s *mcp.Server) { registerBuildConfigTools(s, clients, cfg) })

	tools, err := session.ListTools(t.Context(), nil)
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	for _, tool := range tools.Tools {
		if tool.Name == "buildconfigs_trigger" {
			t.Errorf("write tool %q should not be registered when ReadOnly is true", tool.Name)
		}
	}
}
