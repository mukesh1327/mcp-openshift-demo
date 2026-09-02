package k8sclient

import (
	"os"
	"path/filepath"
	"testing"
)

const testKubeconfig = `
apiVersion: v1
kind: Config
clusters:
- name: test-cluster
  cluster:
    server: https://example-cluster.invalid:6443
contexts:
- name: test-context
  context:
    cluster: test-cluster
    user: test-user
current-context: test-context
users:
- name: test-user
  user:
    token: fake-token
`

func TestBuildRESTConfig_ExplicitKubeconfig(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "kubeconfig")
	if err := os.WriteFile(path, []byte(testKubeconfig), 0o600); err != nil {
		t.Fatalf("writing test kubeconfig: %v", err)
	}

	cfg, err := buildRESTConfig(path)
	if err != nil {
		t.Fatalf("buildRESTConfig() error = %v", err)
	}
	if cfg.Host != "https://example-cluster.invalid:6443" {
		t.Errorf("Host = %q, want the server from the explicit kubeconfig", cfg.Host)
	}
}

func TestBuildRESTConfig_NoConfigAvailable(t *testing.T) {
	// No in-cluster env vars set, and pointing at a kubeconfig that doesn't
	// exist: both discovery paths should fail.
	dir := t.TempDir()
	missing := filepath.Join(dir, "does-not-exist")

	t.Setenv("KUBERNETES_SERVICE_HOST", "")
	t.Setenv("KUBERNETES_SERVICE_PORT", "")

	_, err := buildRESTConfig(missing)
	if err == nil {
		t.Fatalf("buildRESTConfig() error = nil, want error when no config is available")
	}
}
