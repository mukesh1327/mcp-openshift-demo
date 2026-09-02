// Package version holds build-time version metadata, overridable via
// -ldflags "-X mcp-openshift-server/internal/version.Version=...".
package version

var (
	Version   = "dev"
	Commit    = "none"
	BuildDate = "unknown"
)
