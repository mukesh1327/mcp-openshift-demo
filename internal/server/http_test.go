package server

import (
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
	"k8s.io/apimachinery/pkg/runtime"
	discoveryfake "k8s.io/client-go/discovery/fake"
	k8stesting "k8s.io/client-go/testing"
)

func newTestHandler(t *testing.T, disco *discoveryfake.FakeDiscovery) http.Handler {
	t.Helper()
	mcpServer := mcp.NewServer(&mcp.Implementation{Name: "test", Version: "test"}, nil)
	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	return NewHTTPHandler(mcpServer, disco, log)
}

func TestHealthz(t *testing.T) {
	disco := &discoveryfake.FakeDiscovery{Fake: &k8stesting.Fake{}}
	handler := newTestHandler(t, disco)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestReadyz_ClusterReachable(t *testing.T) {
	disco := &discoveryfake.FakeDiscovery{Fake: &k8stesting.Fake{}}
	handler := newTestHandler(t, disco)

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestReadyz_ClusterUnreachable(t *testing.T) {
	disco := &discoveryfake.FakeDiscovery{Fake: &k8stesting.Fake{}}
	disco.Fake.PrependReactor("*", "*", func(k8stesting.Action) (bool, runtime.Object, error) {
		return true, nil, errors.New("cluster unreachable")
	})
	handler := newTestHandler(t, disco)

	req := httptest.NewRequest(http.MethodGet, "/readyz", nil)
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, req)

	if rec.Code != http.StatusServiceUnavailable {
		t.Errorf("status = %d, want 503", rec.Code)
	}
}
