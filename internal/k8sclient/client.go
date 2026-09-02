// Package k8sclient constructs Kubernetes/OpenShift API clients, preferring
// in-cluster ServiceAccount credentials and falling back to standard
// kubeconfig discovery for local development.
package k8sclient

import (
	"fmt"

	"k8s.io/client-go/discovery"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"

	appsv1client "github.com/openshift/client-go/apps/clientset/versioned"
	buildv1client "github.com/openshift/client-go/build/clientset/versioned"
	imagev1client "github.com/openshift/client-go/image/clientset/versioned"
	projectv1client "github.com/openshift/client-go/project/clientset/versioned"
	routev1client "github.com/openshift/client-go/route/clientset/versioned"
)

// Clients bundles every clientset the server's tools need: the core
// Kubernetes clientset plus one versioned clientset per OpenShift API group
// in scope.
type Clients struct {
	Config    *rest.Config
	Discovery discovery.DiscoveryInterface

	Core    kubernetes.Interface
	Apps    appsv1client.Interface
	Build   buildv1client.Interface
	Image   imagev1client.Interface
	Project projectv1client.Interface
	Route   routev1client.Interface
}

// New builds a Clients bundle. It first tries in-cluster ServiceAccount
// configuration (rest.InClusterConfig), which is what applies when running
// as a Pod inside Kubernetes/OpenShift; if that fails (e.g. not running
// in-cluster), it falls back to standard kubeconfig discovery honoring, in
// order: an explicit kubeconfigPath, the KUBECONFIG env var, and
// ~/.kube/config — the same precedence `oc`/`kubectl` use, so an existing
// `oc login` session is picked up automatically.
func New(kubeconfigPath string) (*Clients, error) {
	restConfig, err := buildRESTConfig(kubeconfigPath)
	if err != nil {
		return nil, fmt.Errorf("building cluster config: %w", err)
	}

	// Conservative client-side rate limiting; the cluster's own API
	// priority-and-fairness is the real backstop.
	restConfig.QPS = 20
	restConfig.Burst = 40

	core, err := kubernetes.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building core Kubernetes client: %w", err)
	}
	disco, err := discovery.NewDiscoveryClientForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building discovery client: %w", err)
	}
	appsClient, err := appsv1client.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building OpenShift apps client: %w", err)
	}
	buildClient, err := buildv1client.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building OpenShift build client: %w", err)
	}
	imageClient, err := imagev1client.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building OpenShift image client: %w", err)
	}
	projectClient, err := projectv1client.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building OpenShift project client: %w", err)
	}
	routeClient, err := routev1client.NewForConfig(restConfig)
	if err != nil {
		return nil, fmt.Errorf("building OpenShift route client: %w", err)
	}

	return &Clients{
		Config:    restConfig,
		Discovery: disco,
		Core:      core,
		Apps:      appsClient,
		Build:     buildClient,
		Image:     imageClient,
		Project:   projectClient,
		Route:     routeClient,
	}, nil
}

// buildRESTConfig implements the in-cluster-first, kubeconfig-fallback
// precedence described on New.
func buildRESTConfig(kubeconfigPath string) (*rest.Config, error) {
	if kubeconfigPath == "" {
		if cfg, err := rest.InClusterConfig(); err == nil {
			return cfg, nil
		}
	}

	loadingRules := clientcmd.NewDefaultClientConfigLoadingRules()
	if kubeconfigPath != "" {
		loadingRules.ExplicitPath = kubeconfigPath
	}
	overrides := &clientcmd.ConfigOverrides{}

	cfg, err := clientcmd.NewNonInteractiveDeferredLoadingClientConfig(loadingRules, overrides).ClientConfig()
	if err != nil {
		return nil, fmt.Errorf("loading kubeconfig (explicit path %q, KUBECONFIG env, or ~/.kube/config): %w", kubeconfigPath, err)
	}
	return cfg, nil
}
