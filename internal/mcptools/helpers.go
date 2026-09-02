// Package mcptools registers MCP tools that expose OpenShift/Kubernetes
// cluster operations. Each domain file (pods.go, deployments.go, ...)
// registers the tools for one resource kind.
package mcptools

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/modelcontextprotocol/go-sdk/mcp"

	"mcp-openshift-server/internal/config"
)

// EmptyParams is used by tools that take no input (e.g. cluster-scoped list
// tools). It produces an empty-object JSON Schema rather than requiring
// callers to special-case parameterless tools.
type EmptyParams struct{}

// logger receives structured logs for every tool call. Set once at startup
// via SetLogger; defaults to slog.Default() so tests don't need to configure
// it.
var logger = slog.Default()

// SetLogger installs the logger used by every registered tool handler.
func SetLogger(l *slog.Logger) {
	if l != nil {
		logger = l
	}
}

// wrap adapts a tool handler with structured logging and panic recovery, so
// a bug in one handler returns a clean tool error instead of crashing the
// process (this matters most for the HTTP transport, which serves multiple
// concurrent sessions from one process).
func wrap[In, Out any](name string, h mcp.ToolHandlerFor[In, Out]) mcp.ToolHandlerFor[In, Out] {
	return func(ctx context.Context, req *mcp.CallToolRequest, in In) (result *mcp.CallToolResult, out Out, err error) {
		start := time.Now()
		defer func() {
			if r := recover(); r != nil {
				err = fmt.Errorf("internal error handling tool %q: %v", name, r)
			}
			if err != nil {
				logger.Warn("tool call failed", "tool", name, "duration", time.Since(start), "error", err)
			} else {
				logger.Info("tool call succeeded", "tool", name, "duration", time.Since(start))
			}
		}()
		return h(ctx, req, in)
	}
}

// requireNamespace validates that a namespace parameter was supplied. Every
// namespaced tool calls this before making any cluster API call, so a
// missing namespace never silently falls back to "all namespaces".
func requireNamespace(namespace string) error {
	if namespace == "" {
		return fmt.Errorf("namespace is required")
	}
	return nil
}

// requireName validates that a resource name parameter was supplied.
func requireName(name string) error {
	if name == "" {
		return fmt.Errorf("name is required")
	}
	return nil
}

// withTimeout derives a bounded context for a single cluster API call from
// the tool call's context, so a slow/unresponsive API server can't hang a
// tool call indefinitely.
func withTimeout(ctx context.Context, cfg config.Config) (context.Context, context.CancelFunc) {
	return context.WithTimeout(ctx, cfg.RequestTimeout)
}

// clampLimit bounds a caller-requested list limit to (0, cfg.ListLimit]. A
// non-positive or excessive request silently falls back to cfg.ListLimit
// rather than erroring, since "give me the default page size" is the
// sensible interpretation of an unset limit.
func clampLimit(requested int64, cfg config.Config) int64 {
	if requested <= 0 || requested > cfg.ListLimit {
		return cfg.ListLimit
	}
	return requested
}

// clampTailLines bounds a caller-requested pods_logs tail_lines value to
// (0, cfg.LogsMaxTailLines].
func clampTailLines(requested int64, cfg config.Config) int64 {
	if requested <= 0 || requested > cfg.LogsMaxTailLines {
		return cfg.LogsMaxTailLines
	}
	return requested
}
