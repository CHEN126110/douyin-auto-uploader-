import test from "node:test";
import assert from "node:assert/strict";

import { buildFirstOrderDecisionMatrixRequest } from "../core.js";

test("builds first-order decision matrix requests with baseline and current metrics", () => {
  const request = buildFirstOrderDecisionMatrixRequest({
    baselineMetrics: { id: 22, product_click_count: 3, orders_count: 0 },
    currentMetrics: { id: 23, product_click_count: 8, orders_count: 0 },
    actionId: 3,
    saveGate: { ready_for_human_save_confirmation: true, safe_to_auto_save: false },
    targetNetProfit: 500,
    savedConfirmed: true,
  });

  assert.equal(request.path, "/api/ops/first-order-decision-matrix");
  assert.deepEqual(request.body, {
    baseline_metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    current_metrics: { id: 23, product_click_count: 8, orders_count: 0 },
    action_id: 3,
    save_gate: { ready_for_human_save_confirmation: true, safe_to_auto_save: false },
    target_net_profit: 500,
    saved_confirmed: true,
  });
});
