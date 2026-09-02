package config

import (
	"testing"
	"time"
)

func fakeEnv(m map[string]string) func(string) string {
	return func(k string) string { return m[k] }
}

func TestParse_Defaults(t *testing.T) {
	cfg, err := Parse(nil, fakeEnv(nil))
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if cfg.Transport != TransportStdio {
		t.Errorf("Transport = %q, want %q", cfg.Transport, TransportStdio)
	}
	if cfg.ReadOnly {
		t.Errorf("ReadOnly = true, want false by default")
	}
	if cfg.RequestTimeout != 30*time.Second {
		t.Errorf("RequestTimeout = %s, want 30s", cfg.RequestTimeout)
	}
}

func TestParse_EnvThenFlagPrecedence(t *testing.T) {
	env := fakeEnv(map[string]string{
		"MCP_TRANSPORT": "http",
		"MCP_HTTP_ADDR": ":9999",
		"MCP_READ_ONLY": "true",
	})

	cfg, err := Parse(nil, env)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if cfg.Transport != TransportHTTP || cfg.HTTPAddr != ":9999" || !cfg.ReadOnly {
		t.Fatalf("env not applied: %+v", cfg)
	}

	// Flags must override env.
	cfg, err = Parse([]string{"-transport=stdio", "-http-addr=:7000"}, env)
	if err != nil {
		t.Fatalf("Parse() error = %v", err)
	}
	if cfg.Transport != TransportStdio {
		t.Errorf("flag did not override env: Transport = %q", cfg.Transport)
	}
	if cfg.HTTPAddr != ":7000" {
		t.Errorf("flag did not override env: HTTPAddr = %q", cfg.HTTPAddr)
	}
	if !cfg.ReadOnly {
		t.Errorf("ReadOnly should still be true from env")
	}
}

func TestValidate(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*Config)
		wantErr bool
	}{
		{"valid defaults", func(c *Config) {}, false},
		{"bad transport", func(c *Config) { c.Transport = "carrier-pigeon" }, true},
		{"http empty addr", func(c *Config) { c.Transport = TransportHTTP; c.HTTPAddr = "" }, true},
		{"non-positive timeout", func(c *Config) { c.RequestTimeout = 0 }, true},
		{"non-positive list limit", func(c *Config) { c.ListLimit = 0 }, true},
		{"non-positive tail lines", func(c *Config) { c.LogsMaxTailLines = -1 }, true},
		{"bad log level", func(c *Config) { c.LogLevel = "verbose" }, true},
		{"bad log format", func(c *Config) { c.LogFormat = "xml" }, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := Default()
			tt.mutate(&cfg)
			err := cfg.Validate()
			if (err != nil) != tt.wantErr {
				t.Errorf("Validate() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}
