// Package server wires an *mcp.Server up to a concrete transport: stdio for
// local MCP clients, or streamable HTTP for remote/in-cluster deployment.
package server

import (
	"context"
	"fmt"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// RunStdio serves the given MCP server over stdin/stdout until the client
// disconnects or ctx is canceled.
func RunStdio(ctx context.Context, mcpServer *mcp.Server) error {
	if err := mcpServer.Run(ctx, &mcp.StdioTransport{}); err != nil {
		return fmt.Errorf("stdio transport: %w", err)
	}
	return nil
}
