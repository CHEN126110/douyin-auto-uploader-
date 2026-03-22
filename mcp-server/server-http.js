#!/usr/bin/env node

import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";
import { createDouyinPublisherServer, getConfiguredBackendUrl } from "./core.js";

const host = process.env.MCP_HTTP_HOST || "127.0.0.1";
const port = Number(process.env.MCP_HTTP_PORT || "3300");

const app = createMcpExpressApp({ host });

app.post("/mcp", async (req, res) => {
  const server = createDouyinPublisherServer();

  try {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined,
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);

    res.on("close", () => {
      transport.close();
      server.close();
    });
  } catch (error) {
    console.error("[douyin-publisher-mcp] HTTP transport error:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: {
          code: -32603,
          message: "Internal server error",
        },
        id: null,
      });
    }
  }
});

app.get("/mcp", async (_req, res) => {
  res.writeHead(405).end(
    JSON.stringify({
      jsonrpc: "2.0",
      error: {
        code: -32000,
        message: "Method not allowed.",
      },
      id: null,
    })
  );
});

app.delete("/mcp", async (_req, res) => {
  res.writeHead(405).end(
    JSON.stringify({
      jsonrpc: "2.0",
      error: {
        code: -32000,
        message: "Method not allowed.",
      },
      id: null,
    })
  );
});

app.get("/", (_req, res) => {
  res.json({
    name: "douyin-publisher-mcp",
    transport: "streamable_http",
    endpoint: `http://${host}:${port}/mcp`,
    backend: getConfiguredBackendUrl(),
  });
});

app.listen(port, host, (error) => {
  if (error) {
    console.error("[douyin-publisher-mcp] failed to start HTTP server:", error);
    process.exit(1);
  }

  console.log(
    `[douyin-publisher-mcp] streamable_http listening on http://${host}:${port}/mcp (backend=${getConfiguredBackendUrl()})`
  );
});
