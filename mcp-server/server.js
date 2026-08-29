#!/usr/bin/env node

import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { createDouyinPublisherServer, getConfiguredBackendUrl } from "./core.js";
import { getDefaultCdpListUrl } from "./cdp-client.js";

async function main() {
  const server = createDouyinPublisherServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(
    `[douyin-publisher-mcp] stdio connected, backend=${getConfiguredBackendUrl()}, cdp_list=${getDefaultCdpListUrl()}`
  );
}

main().catch((error) => {
  console.error("[douyin-publisher-mcp] fatal error:", error);
  process.exit(1);
});
