import test from "node:test";
import assert from "node:assert/strict";
import http from "node:http";

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createDouyinPublisherServer } from "../core.js";

function json(response, payload) {
  response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(payload));
}

test("agent can read shop and Taobao status and explicitly restore the browser", async () => {
  const requests = [];
  const backend = http.createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    requests.push({ method: request.method, path: url.pathname });
    if (url.pathname === "/api/shop/current") {
      return json(response, { success: true, data: { status: "no_browser", shop_id: null } });
    }
    if (url.pathname === "/api/shop/restore" && request.method === "POST") {
      return json(response, { success: true, data: { recovery_attempted: true, browser_opened: true,
        shop: { status: "no_browser" } } });
    }
    if (url.pathname === "/api/taobao/publish/tasks") {
      return json(response, { success: true, data: { tasks: [{ task_id: "task-1", status: "succeeded" }] } });
    }
    if (url.pathname === "/api/taobao/publish/status/task-1") {
      return json(response, { success: true, data: { task_id: "task-1", status: "succeeded",
        publish_confirmed: false } });
    }
    return json(response, { success: false, msg: `Unexpected ${request.method} ${url.pathname}` });
  });
  await new Promise(resolve => backend.listen(0, "127.0.0.1", resolve));
  const previous = process.env.DOUYIN_BACKEND_URL;
  process.env.DOUYIN_BACKEND_URL = `http://127.0.0.1:${backend.address().port}`;
  const mcp = createDouyinPublisherServer();
  const client = new Client({ name: "agent-status-test", version: "1.0.0" }, { capabilities: {} });
  const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
  try {
    await Promise.all([mcp.connect(serverTransport), client.connect(clientTransport)]);
    const tools = await client.listTools();
    const names = new Set(tools.tools.map(tool => tool.name));
    for (const name of ["get_shop_session", "restore_shop_session",
      "list_taobao_publish_tasks", "get_taobao_publish_status", "get_product_detail", "list_sku_assets"]) {
      assert.ok(names.has(name), `missing tool ${name}`);
    }

    const shop = await client.callTool({ name: "get_shop_session", arguments: {} });
    assert.equal(shop.structuredContent.data.status, "no_browser");

    const tasks = await client.callTool({ name: "list_taobao_publish_tasks", arguments: {} });
    assert.equal(tasks.structuredContent.data.tasks[0].task_id, "task-1");

    const task = await client.callTool({ name: "get_taobao_publish_status", arguments: { taskId: "task-1" } });
    assert.equal(task.structuredContent.data.publish_confirmed, false);

    const restored = await client.callTool({ name: "restore_shop_session", arguments: {} });
    assert.equal(restored.structuredContent.data.browser_opened, true);
    assert.equal(restored.structuredContent.data.shop.status, "no_browser",
      "opening a browser must not be misrepresented as login recovery");

    const resources = await client.listResources();
    const uris = new Set(resources.resources.map(resource => resource.uri));
    assert.ok(uris.has("douyin://shop/session"));
    assert.ok(uris.has("douyin://taobao/publish/tasks"));
    const resource = await client.readResource({ uri: "douyin://shop/session" });
    assert.equal(JSON.parse(resource.contents[0].text).data.status, "no_browser");

    const restoreRequest = requests.find(request => request.path === "/api/shop/restore");
    assert.equal(restoreRequest.method, "POST");
  } finally {
    await client.close();
    await mcp.close();
    await new Promise(resolve => backend.close(resolve));
    if (previous === undefined) delete process.env.DOUYIN_BACKEND_URL;
    else process.env.DOUYIN_BACKEND_URL = previous;
  }
});
