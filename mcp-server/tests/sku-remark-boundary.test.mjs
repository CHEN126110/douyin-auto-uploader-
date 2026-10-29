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

test("SKU remarks stay per-row and never overwrite the product remark", async () => {
  const saveRequests = [];
  const productRemark = "商品级卖点备注";
  const originalSku = { path: "SKU/a.jpg", name: "白色 / 均码", price: 5.9,
    stock: 100, file_name: "a.jpg", remark: "旧SKU备注" };
  const updatedSku = { ...originalSku, remark: "新的SKU专属备注" };
  let detail = { id: 1, title: "标题", remark: productRemark, repo: 100, clazz: 2,
    path: "SKU", content: [originalSku] };
  const backend = http.createServer((request, response) => {
    const url = new URL(request.url, "http://127.0.0.1");
    if (url.pathname === "/load_detail") return json(response, { success: true, data: detail });
    if (url.pathname === "/save_info" && request.method === "POST") {
      let body = "";
      request.on("data", chunk => { body += chunk; });
      request.on("end", () => {
        saveRequests.push(JSON.parse(body));
        detail = { ...detail, content: [updatedSku] };
        return json(response, { success: true, data: { id: 1 } });
      });
      return;
    }
    return json(response, { success: false, msg: `Unexpected ${request.method} ${url.pathname}` });
  });
  await new Promise(resolve => backend.listen(0, "127.0.0.1", resolve));
  const previous = process.env.DOUYIN_BACKEND_URL;
  process.env.DOUYIN_BACKEND_URL = `http://127.0.0.1:${backend.address().port}`;
  const mcp = createDouyinPublisherServer();
  const client = new Client({ name: "sku-remark-test", version: "1.0.0" }, { capabilities: {} });
  const [serverTransport, clientTransport] = InMemoryTransport.createLinkedPair();
  try {
    await Promise.all([mcp.connect(serverTransport), client.connect(clientTransport)]);
    const assets = await client.callTool({ name: "list_sku_assets", arguments: { recordId: 1 } });
    assert.equal(assets.structuredContent.product.remark, productRemark);
    assert.equal(assets.structuredContent.skus[0].remark, "旧SKU备注");
    assert.equal(assets.structuredContent.skus[0].stock, 100);

    await client.callTool({ name: "update_product_info", arguments: {
      recordId: 1,
      skuUpdates: [{ path: "SKU/a.jpg", remark: "新的SKU专属备注" }],
    } });
    assert.equal(saveRequests.length, 1);
    const saved = saveRequests[0];
    assert.equal(saved.remark, productRemark, "product-level remark must remain unchanged");
    assert.equal(saved.attr_remark_1, "新的SKU专属备注");
    assert.equal(saved.attr_name_1, originalSku.name);
    assert.equal(saved.attr_price_1, originalSku.price);
  } finally {
    await client.close();
    await mcp.close();
    await new Promise(resolve => backend.close(resolve));
    if (previous === undefined) delete process.env.DOUYIN_BACKEND_URL;
    else process.env.DOUYIN_BACKEND_URL = previous;
  }
});
