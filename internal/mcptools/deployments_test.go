package mcptools

import (
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	appsv1 "k8s.io/api/apps/v1"
	autoscalingv1 "k8s.io/api/autoscaling/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/client-go/kubernetes/fake"
	clienttesting "k8s.io/client-go/testing"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

func newDeploymentFake(t *testing.T) (*fake.Clientset, *k8sclient.Clients) {
	t.Helper()
	core := fake.NewSimpleClientset(&appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: "web", Namespace: "demo"},
		Spec:       appsv1.DeploymentSpec{Replicas: int32Ptr(2)},
	})
	return core, &k8sclient.Clients{Core: core}
}

// TestDeploymentsScale_OnlyPatchesScaleSubresource is the regression guard
// for scope creep: deployments_scale must do exactly one thing — update the
// /scale subresource — and nothing else (no delete, no create, no update of
// unrelated fields).
func TestDeploymentsScale_OnlyPatchesScaleSubresource(t *testing.T) {
	core, clients := newDeploymentFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentTools(s, clients, cfg) })

	var scale autoscalingv1.Scale
	callTool(t, session, "deployments_scale", map[string]any{
		"namespace": "demo", "name": "web", "replicas": float64(5),
	}, &scale)

	// The fake clientset's /scale subresource support has known quirks
	// around persisting into the object tracker, so assert on the action
	// log (what request was actually issued) and the handler's own return
	// value, rather than re-fetching the Deployment afterward.
	actions := core.Actions()
	if len(actions) != 1 {
		t.Fatalf("got %d actions, want exactly 1: %+v", len(actions), actions)
	}
	a := actions[0]
	if a.GetVerb() != "update" || a.GetResource().Resource != "deployments" || a.GetSubresource() != "scale" {
		t.Fatalf("action = %s %s/%s, want update on deployments/scale", a.GetVerb(), a.GetResource().Resource, a.GetSubresource())
	}
	if scale.Spec.Replicas != 5 {
		t.Errorf("returned scale replicas = %d, want 5", scale.Spec.Replicas)
	}
}

func TestDeploymentsScale_RejectsOutOfRangeReplicas(t *testing.T) {
	core, clients := newDeploymentFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentTools(s, clients, cfg) })

	result, err := session.CallTool(t.Context(), &mcp.CallToolParams{
		Name:      "deployments_scale",
		Arguments: map[string]any{"namespace": "demo", "name": "web", "replicas": float64(-1)},
	})
	if err != nil {
		t.Fatalf("CallTool: %v", err)
	}
	if !result.IsError {
		t.Fatalf("expected error for negative replicas")
	}
	if len(core.Actions()) != 0 {
		t.Fatalf("expected no cluster calls for a rejected request, got %+v", core.Actions())
	}
}

// TestDeploymentsRestart_OnlyPatchesPodTemplateAnnotation guards against the
// restart tool turning into a broader "update whatever" operation: it must
// issue exactly one strategic-merge patch, on the deployment itself (no
// subresource), not a full object replace.
func TestDeploymentsRestart_OnlyPatchesPodTemplateAnnotation(t *testing.T) {
	core, clients := newDeploymentFake(t)
	cfg := config.Default()
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentTools(s, clients, cfg) })

	callTool(t, session, "deployments_restart", map[string]any{"namespace": "demo", "name": "web"}, nil)

	actions := core.Actions()
	if len(actions) != 1 {
		t.Fatalf("got %d actions, want exactly 1: %+v", len(actions), actions)
	}
	patchAction, ok := actions[0].(clienttesting.PatchAction)
	if !ok {
		t.Fatalf("action = %T, want a patch action", actions[0])
	}
	if patchAction.GetPatchType() != types.StrategicMergePatchType {
		t.Errorf("patch type = %s, want StrategicMergePatchType", patchAction.GetPatchType())
	}
	if patchAction.GetSubresource() != "" {
		t.Errorf("patch subresource = %q, want none (patching the deployment itself)", patchAction.GetSubresource())
	}

	dep, err := core.AppsV1().Deployments("demo").Get(t.Context(), "web", metav1.GetOptions{})
	if err != nil {
		t.Fatalf("Get after restart: %v", err)
	}
	if dep.Spec.Template.Annotations[restartedAtAnnotation] == "" {
		t.Errorf("expected %s annotation to be set on pod template", restartedAtAnnotation)
	}
}

func TestDeploymentTools_ReadOnlyModeHidesWriteTools(t *testing.T) {
	_, clients := newDeploymentFake(t)
	cfg := config.Default()
	cfg.ReadOnly = true
	session := newTestSession(t, func(s *mcp.Server) { registerDeploymentTools(s, clients, cfg) })

	tools, err := session.ListTools(t.Context(), nil)
	if err != nil {
		t.Fatalf("ListTools: %v", err)
	}
	for _, tool := range tools.Tools {
		if tool.Name == "deployments_scale" || tool.Name == "deployments_restart" {
			t.Errorf("write tool %q should not be registered when ReadOnly is true", tool.Name)
		}
	}
}

func int32Ptr(i int32) *int32 { return &i }
