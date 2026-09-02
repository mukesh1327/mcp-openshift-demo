package mcptools

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// newTestSession spins up an in-memory MCP client/server pair, invokes
// register on the server, and returns a connected client session. This lets
// tests exercise tool handlers through the same path a real MCP client
// uses (typed input validation, JSON Schema, error conversion) rather than
// calling handler closures directly.
func newTestSession(t *testing.T, register func(*mcp.Server)) *mcp.ClientSession {
	t.Helper()

	server := mcp.NewServer(&mcp.Implementation{Name: "test-server", Version: "test"}, nil)
	register(server)

	serverTransport, clientTransport := mcp.NewInMemoryTransports()

	ctx := context.Background()
	if _, err := server.Connect(ctx, serverTransport, nil); err != nil {
		t.Fatalf("server.Connect: %v", err)
	}

	client := mcp.NewClient(&mcp.Implementation{Name: "test-client", Version: "test"}, nil)
	session, err := client.Connect(ctx, clientTransport, nil)
	if err != nil {
		t.Fatalf("client.Connect: %v", err)
	}
	t.Cleanup(func() { _ = session.Close() })
	return session
}

// callTool invokes a tool by name and decodes its JSON text content into
// out (pass a pointer, or nil to skip decoding). It fails the test if the
// call itself errors at the protocol level.
func callTool(t *testing.T, session *mcp.ClientSession, name string, args map[string]any, out any) *mcp.CallToolResult {
	t.Helper()
	result, err := session.CallTool(context.Background(), &mcp.CallToolParams{
		Name:      name,
		Arguments: args,
	})
	if err != nil {
		t.Fatalf("CallTool(%s): %v", name, err)
	}
	if out != nil && !result.IsError {
		text := firstText(t, result)
		if err := json.Unmarshal([]byte(text), out); err != nil {
			t.Fatalf("CallTool(%s): decoding result content: %v\ncontent: %s", name, err, text)
		}
	}
	return result
}

func firstText(t *testing.T, result *mcp.CallToolResult) string {
	t.Helper()
	if len(result.Content) == 0 {
		t.Fatalf("tool result has no content")
	}
	tc, ok := result.Content[0].(*mcp.TextContent)
	if !ok {
		t.Fatalf("tool result content[0] is %T, want *mcp.TextContent", result.Content[0])
	}
	return tc.Text
}

// errorText returns the text of an error result, for asserting on error
// message content.
func errorText(t *testing.T, result *mcp.CallToolResult) string {
	t.Helper()
	if !result.IsError {
		t.Fatalf("expected an error result, got a success result")
	}
	return firstText(t, result)
}
