import test from "node:test";
import assert from "node:assert/strict";

import { buildConversionAssetPackRequest } from "../core.js";

test("builds no-brand conversion asset pack requests with audit and product context", () => {
  const request = buildConversionAssetPackRequest({
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    product: {
      action_id: 3,
      product_id: "3811995393416364123",
      title: "小雏菊碎花袜子女春夏新款镂空网眼中筒袜",
      sale_price: 20,
    },
    detailAudit: {
      stage: "detail_conversion_bottleneck",
      brand_gate: { ready: true, required_value: "无品牌" },
    },
    suggestions: {
      guide_short_title: { text: "小雏菊碎花春夏中筒袜" },
    },
    targetNetProfit: 500,
  });

  assert.equal(request.path, "/api/ops/conversion-asset-pack");
  assert.deepEqual(request.body, {
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    product: {
      action_id: 3,
      product_id: "3811995393416364123",
      title: "小雏菊碎花袜子女春夏新款镂空网眼中筒袜",
      sale_price: 20,
    },
    detail_audit: {
      stage: "detail_conversion_bottleneck",
      brand_gate: { ready: true, required_value: "无品牌" },
    },
    suggestions: {
      guide_short_title: { text: "小雏菊碎花春夏中筒袜" },
    },
    target_net_profit: 500,
  });
});
