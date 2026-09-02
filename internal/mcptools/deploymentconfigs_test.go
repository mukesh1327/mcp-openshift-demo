package mcptools

import (
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	osappsv1 "github.com/openshift/api/apps/v1"
	appsfake "github.com/openshift/client-go/apps/clientset/versioned/fake"
	extensionsv1beta1 "k8s.io/api/extensions/v1beta1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func newDeploymentConfigFake(t *testing.T) (*appsfake.Clientset, *k8sclient.Clients) {
	t.Helper()
	apps := appsfake.NewSimpleClientset(&osappsv1.DeploymentConfig{
		ObjectMeta: metav1.ObjectMeta{Name: "web", Namespace: "demo"},
		Spec:       osappsv1.DeploymentConfigSpec{Replicas: 2},
	})
	return apps, &k8sclient.Clients{Apps: apps}
}

func TestDeploymentConfigsScale_OnlyHitsScaleSubresource(t *testing.T) {
	apps, clients := newDeploymentConfigFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentConfigTools(s, clients, cfg) })

	var scale extensionsv1beta1.Scale
	callTool(t, session, "deploymentconfigs_scale", map[string]any{
		"namespace": "demo", "name": "web", "replicas": float64(7),
	}, &scale)

	actions := apps.Actions()
	if len(actions) != 1 {
		t.Fatalf("got %d actions, want exactly 1: %+v", len(actions), actions)
	}
	a := actions[0]
	if a.GetVerb() != "update" || a.GetResource().Resource != "deploymentconfigs" || a.GetSubresource() != "scale" {
		t.Fatalf("action = %s %s/%s, want update on deploymentconfigs/scale", a.GetVerb(), a.GetResource().Resource, a.GetSubresource())
	}
	if scale.Spec.Replicas != 7 {
		t.Errorf("returned scale replicas = %d, want 7", scale.Spec.Replicas)
	}
}

// TestDeploymentConfigsRestart_OnlyInstantiates guards that the restart tool
// issues exactly one Instantiate (create on the /instantiate subresource),
// mirroring `oc rollout latest`, and nothing else — no delete, no direct
// spec edit.
func TestDeploymentConfigsRestart_OnlyInstantiates(t *testing.T) {
	apps, clients := newDeploymentConfigFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentConfigTools(s, clients, cfg) })

	callTool(t, session, "deploymentconfigs_restart", map[string]any{"namespace": "demo", "name": "web"}, nil)

	actions := apps.Actions()
	if len(actions) != 1 {
		t.Fatalf("got %d actions, want exactly 1: %+v", len(actions), actions)
	}
	a := actions[0]
	if a.GetVerb() != "create" || a.GetResource().Resource != "deploymentconfigs" || a.GetSubresource() != "instantiate" {
		t.Fatalf("action = %s %s/%s, want create on deploymentconfigs/instantiate", a.GetVerb(), a.GetResource().Resource, a.GetSubresource())
	}
}

func TestDeploymentConfigTools_ReadOnlyModeHidesWriteTools(t *testing.T) {
	_, clients := newDeploymentConfigFake(t)
	cfg := config.Default()
	cfg.ReadOnly = true
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentConfigTools(s, clients, cfg) })

	tools, err := session.ListTools(t.Context(), nil)
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	for _, tool := range tools.Tools {
		if tool.Name == "deploymentconfigs_scale" || tool.Name == "deploymentconfigs_restart" {
			t.Errorf("write tool %q should not be registered when ReadOnly is true", tool.Name)
		}
	}
}
