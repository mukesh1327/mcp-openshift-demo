// Package config parses server configuration from CLI flags and environment
// variables. Flags take precedence over environment variables, which take
// precedence over defaults.
package config

import (
	"flag"
	"fmt"
	"os"
	"strconv"
	"time"
)

const (
	TransportStdio = "stdio"
	TransportHTTP  = "http"
)

// Config holds all runtime configuration for the server.
type Config struct {
	// Transport selects how the MCP server is exposed: "stdio" or "http".
	Transport string
	// HTTPAddr is the listen address used when Transport is "http".
	HTTPAddr string

	// KubeconfigPath overrides the standard kubeconfig discovery path.
	// Empty means: try in-cluster config, then fall back to the standard
	// kubeconfig loading rules (KUBECONFIG env, ~/.kube/config).
	KubeconfigPath string

	// RequestTimeout bounds every individual Kubernetes/OpenShift API call.
	RequestTimeout time.Duration

	// ListLimit caps the number of items returned by any list tool.
	ListLimit int64
	// LogsMaxTailLines caps the tail_lines parameter accepted by pods_logs.
	LogsMaxTailLines int64

	// ReadOnly disables registration of every write tool when true.
	ReadOnly bool

	// LogLevel is one of: debug, info, warn, error.
	LogLevel string
	// LogFormat is one of: json, text.
	LogFormat string
}

// Default returns a Config populated with sane defaults.
func Default() Config {
	return Config{
		Transport:        TransportStdio,
		HTTPAddr:         ":8080",
		KubeconfigPath:   "",
		RequestTimeout:   30 * time.Second,
		ListLimit:        500,
		LogsMaxTailLines: 5000,
		ReadOnly:         false,
		LogLevel:         "info",
		LogFormat:        "json",
	}
}

// Parse builds a Config from environment variables and then CLI flags
// (flags win on conflict), validating the result before returning it.
func Parse(args []string, getenv func(string) string) (Config, error) {
	cfg := Default()
	applyEnv(&cfg, getenv)

	fs := flag.NewFlagSet("mcp-openshift-server", flag.ContinueOnError)
	fs.StringVar(&cfg.Transport, "transport", cfg.Transport, `MCP transport: "stdio" or "http"`)
	fs.StringVar(&cfg.HTTPAddr, "http-addr", cfg.HTTPAddr, "listen address when -transport=http")
	fs.StringVar(&cfg.KubeconfigPath, "kubeconfig", cfg.KubeconfigPath, "path to kubeconfig (default: in-cluster, then standard kubeconfig discovery)")
	fs.DurationVar(&cfg.RequestTimeout, "request-timeout", cfg.RequestTimeout, "timeout applied to every cluster API call")
	fs.Int64Var(&cfg.ListLimit, "list-limit", cfg.ListLimit, "maximum items returned by list tools")
	fs.Int64Var(&cfg.LogsMaxTailLines, "logs-max-tail-lines", cfg.LogsMaxTailLines, "maximum tail_lines accepted by pods_logs")
	fs.BoolVar(&cfg.ReadOnly, "read-only", cfg.ReadOnly, "disable all write tools")
	fs.StringVar(&cfg.LogLevel, "log-level", cfg.LogLevel, "log level: debug, info, warn, error")
	fs.StringVar(&cfg.LogFormat, "log-format", cfg.LogFormat, "log format: json, text")

	if err := fs.Parse(args); err != nil {
		return Config{}, err
	}

	if err := cfg.Validate(); err != nil {
		return Config{}, err
	}
	return cfg, nil
}

func applyEnv(cfg *Config, getenv func(string) string) {
	if v := getenv("MCP_TRANSPORT"); v != "" {
		cfg.Transport = v
	}
	if v := getenv("MCP_HTTP_ADDR"); v != "" {
		cfg.HTTPAddr = v
	}
	if v := getenv("KUBECONFIG"); v != "" {
		cfg.KubeconfigPath = v
	}
	if v := getenv("MCP_REQUEST_TIMEOUT"); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			cfg.RequestTimeout = d
		}
	}
	if v := getenv("MCP_LIST_LIMIT"); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			cfg.ListLimit = n
		}
	}
	if v := getenv("MCP_LOGS_MAX_TAIL_LINES"); v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			cfg.LogsMaxTailLines = n
		}
	}
	if v := getenv("MCP_READ_ONLY"); v != "" {
		if b, err := strconv.ParseBool(v); err == nil {
			cfg.ReadOnly = b
		}
	}
	if v := getenv("MCP_LOG_LEVEL"); v != "" {
		cfg.LogLevel = v
	}
	if v := getenv("MCP_LOG_FORMAT"); v != "" {
		cfg.LogFormat = v
	}
}

// Validate checks the config for internal consistency. It performs no I/O
// and requires no cluster access, so it is fully unit-testable.
func (c Config) Validate() error {
	switch c.Transport {
	case TransportStdio, TransportHTTP:
	default:
		return fmt.Errorf("invalid -transport %q: must be %q or %q", c.Transport, TransportStdio, TransportHTTP)
	}
	if c.Transport == TransportHTTP && c.HTTPAddr == "" {
		return fmt.Errorf("-http-addr must not be empty when -transport=%s", TransportHTTP)
	}
	if c.RequestTimeout <= 0 {
		return fmt.Errorf("-request-timeout must be positive, got %s", c.RequestTimeout)
	}
	if c.ListLimit <= 0 {
		return fmt.Errorf("-list-limit must be positive, got %d", c.ListLimit)
	}
	if c.LogsMaxTailLines <= 0 {
		return fmt.Errorf("-logs-max-tail-lines must be positive, got %d", c.LogsMaxTailLines)
	}
	switch c.LogLevel {
	case "debug", "info", "warn", "error":
	default:
		return fmt.Errorf("invalid -log-level %q: must be one of debug, info, warn, error", c.LogLevel)
	}
	switch c.LogFormat {
	case "json", "text":
	default:
		return fmt.Errorf("invalid -log-format %q: must be json or text", c.LogFormat)
	}
	return nil
}

// Getenv is the standard os.Getenv, provided as a convenience default for
// callers of Parse that don't need to inject a fake environment.
func Getenv(key string) string {
	return os.Getenv(key)
}
