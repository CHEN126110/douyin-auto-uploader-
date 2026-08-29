import test from "node:test";
import assert from "node:assert/strict";

import { buildProfitLadderTo500Request } from "../core.js";

test("builds profit ladder requests with product and cost scenarios", () => {
  const request = buildProfitLadderTo500Request({
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    product: {
      action_id: 3,
      product_id: "3811995393416364123",
      sale_price: 20,
    },
    costScenarios: [
      { scenario_id: "low_cost", goods_cost: 2 },
      { scenario_id: "mid_cost", goods_cost: 5 },
    ],
    targetNetProfit: 500,
  });

  assert.equal(request.path, "/api/ops/profit-ladder-to-500");
  assert.deepEqual(request.body, {
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    product: {
      action_id: 3,
      product_id: "3811995393416364123",
      sale_price: 20,
    },
    cost_scenarios: [
      { scenario_id: "low_cost", goods_cost: 2 },
      { scenario_id: "mid_cost", goods_cost: 5 },
    ],
    target_net_profit: 500,
  });
});
