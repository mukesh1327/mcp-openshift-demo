package mcptools

import (
	"context"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	buildv1 "github.com/openshift/api/build/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"mcp-openshift-server/internal/config"
	"mcp-openshift-server/internal/k8sclient"
)

type BuildConfigTriggerParams struct {
	Namespace string            `json:"namespace" jsonschema:"namespace containing the BuildConfig"`
	Name      string            `json:"name" jsonschema:"BuildConfig name to trigger a new Build from"`
	CommitRef string            `json:"commit_ref,omitempty" jsonschema:"optional git commit SHA or ref to build instead of the BuildConfig's configured branch"`
	Env       map[string]string `json:"env,omitempty" jsonschema:"optional additional environment variables to pass into the builder container"`
}

func registerBuildConfigTools(server *mcp.Server, clients *k8sclient.Clients, cfg config.Config) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "buildconfigs_list",
		Description: "Read-only. OpenShift only. List BuildConfigs in a namespace, optionally filtered by label selector.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("buildconfigs_list", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceLabelSelectorParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		list, err := clients.Build.BuildV1().BuildConfigs(in.Namespace).List(ctx, metav1.ListOptions{
			LabelSelector: in.LabelSelector,
			Limit:         clampLimit(0, cfg),
		})
		if err != nil {
			return nil, nil, wrapAPIError("listing buildconfigs in namespace "+in.Namespace, err)
		}
		return nil, list, nil
	}))

	mcp.AddTool(server, &mcp.Tool{
		Name:        "buildconfigs_get",
		Description: "Read-only. OpenShift only. Get the full structured spec of a single BuildConfig.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: true},
	}, wrap("buildconfigs_get", func(ctx context.Context, _ *mcp.CallToolRequest, in NamespaceNameParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		bc, err := clients.Build.BuildV1().BuildConfigs(in.Namespace).Get(ctx, in.Name, metav1.GetOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("getting buildconfig "+in.Namespace+"/"+in.Name, err)
		}
		return nil, bc, nil
	}))

	if cfg.ReadOnly {
		return
	}

	mcp.AddTool(server, &mcp.Tool{
		Name:        "buildconfigs_trigger",
		Description: "Safe write. OpenShift only. Trigger a new Build from a BuildConfig (equivalent to `oc start-build`). Creates exactly one new Build object; does not modify the BuildConfig itself.",
		Annotations: &mcp.ToolAnnotations{ReadOnlyHint: false, DestructiveHint: ptrBool(false), IdempotentHint: false},
	}, wrap("buildconfigs_trigger", func(ctx context.Context, _ *mcp.CallToolRequest, in BuildConfigTriggerParams) (*mcp.CallToolResult, any, error) {
		if err := requireNamespace(in.Namespace); err != nil {
			return nil, nil, err
		}
		if err := requireName(in.Name); err != nil {
			return nil, nil, err
		}
		ctx, cancel := withTimeout(ctx, cfg)
		defer cancel()

		req := &buildv1.BuildRequest{
			ObjectMeta: metav1.ObjectMeta{Name: in.Name},
		}
		if in.CommitRef != "" {
			req.Revision = &buildv1.SourceRevision{
				Type: buildv1.BuildSourceGit,
				Git:  &buildv1.GitSourceRevision{Commit: in.CommitRef},
			}
		}
		for k, v := range in.Env {
			req.Env = append(req.Env, corev1.EnvVar{Name: k, Value: v})
		}

		build, err := clients.Build.BuildV1().BuildConfigs(in.Namespace).Instantiate(ctx, in.Name, req, metav1.CreateOptions{})
		if err != nil {
			return nil, nil, wrapAPIError("triggering build from buildconfig "+in.Namespace+"/"+in.Name, err)
		}
		return nil, build, nil
	}))
}
