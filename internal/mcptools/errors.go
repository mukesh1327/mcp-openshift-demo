package mcptools

import (
	"context"
	"errors"
	"fmt"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
)

// wrapAPIError turns a raw Kubernetes/OpenShift client error into a clear,
// actionable message. The go-sdk's typed tool handlers automatically convert
// a returned error into an MCP tool error (CallToolResult.IsError), so
// handlers only need to return a good message — never a Go panic or a raw
// client-go error string.
func wrapAPIError(action string, err error) error {
	if err == nil {
		return nil
	}
	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return fmt.Errorf("%s: timed out waiting for the cluster to respond", action)
	case apierrors.IsNotFound(err):
		return fmt.Errorf("%s: resource not found", action)
	case apierrors.IsForbidden(err):
		return fmt.Errorf("%s: forbidden — the server's ServiceAccount/user is not permitted to do this; check the RBAC Role/ClusterRole granted to it", action)
	case apierrors.IsUnauthorized(err):
		return fmt.Errorf("%s: unauthorized — the cluster rejected the server's credentials", action)
	case apierrors.IsTimeout(err), apierrors.IsServerTimeout(err):
		return fmt.Errorf("%s: the cluster API timed out", action)
	case apierrors.IsConflict(err):
		return fmt.Errorf("%s: conflict — the resource was modified concurrently, retry", action)
	case apierrors.IsInvalid(err):
		return fmt.Errorf("%s: invalid request: %v", action, err)
	case apierrors.IsTooManyRequests(err):
		return fmt.Errorf("%s: the cluster API is rate-limiting requests, retry later", action)
	default:
		return fmt.Errorf("%s: %w", action, err)
	}
}
