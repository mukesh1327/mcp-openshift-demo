package k8sclient

import (
	"context"
	"fmt"

	"k8s.io/client-go/discovery"
)

// openshiftMarkerGroup is an API group present only on OpenShift clusters.
// Its presence is used to decide whether to register OpenShift-only tools
// (routes, deploymentconfigs, builds, buildconfigs, imagestreams, projects).
const openshiftMarkerGroup = "route.openshift.io"

// DetectOpenShift reports whether the cluster reachable through disco
// exposes OpenShift APIs. It performs a single discovery call and is safe
// to call once at startup.
func DetectOpenShift(ctx context.Context, disco discovery.DiscoveryInterface) (bool, error) {
	groups, err := disco.ServerGroups()
	if err != nil {
		return false, fmt.Errorf("listing API groups: %w", err)
	}
	for _, g := range groups.Groups {
		if g.Name == openshiftMarkerGroup {
			return true, nil
		}
	}
	return false, nil
}
