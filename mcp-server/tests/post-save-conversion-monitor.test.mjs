import test from "node:test";
import assert from "node:assert/strict";

import { buildPostSaveConversionMonitorRequest } from "../core.js";

test("builds post-save conversion monitor requests with safety-gate fields", () => {
  const request = buildPostSaveConversionMonitorRequest({
    metrics: {
      product_exposure_count: 24,
      product_click_count: 2,
      orders_count: 0,
      net_profit_verified: false,
    },
    action: {
      id: 3,
      product_id: "3811995393416364123",
    },
    saveGate: {
      ready_for_human_save_confirmation: true,
      safe_to_auto_save: false,
    },
    conversionExperimentPlan: {
      stage: "detail_conversion_bottleneck",
    },
    targetNetProfit: 500,
    savedConfirmed: false,
  });

  assert.equal(request.path, "/api/ops/post-save-conversion-monitor");
  assert.deepEqual(request.body, {
    metrics: {
      product_exposure_count: 24,
      product_click_count: 2,
      orders_count: 0,
      net_profit_verified: false,
    },
    action: {
      id: 3,
      product_id: "3811995393416364123",
    },
    save_gate: {
      ready_for_human_save_confirmation: true,
      safe_to_auto_save: false,
    },
    conversion_experiment_plan: {
      stage: "detail_conversion_bottleneck",
    },
    target_net_profit: 500,
    saved_confirmed: false,
  });
});
