import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSearchConversionWorkPackageRequest,
  buildStrategyActionReconcileRequest,
} from "../core.js";

test("builds search conversion work package requests with snapshot and action context", () => {
  const request = buildSearchConversionWorkPackageRequest({
    metrics: { id: 24, product_exposure_count: 45, product_click_count: 3, orders_count: 0 },
    productIssueActions: [{ id: 1, title: "韩系波点中筒袜", recent_30d_sales: 7 }],
    actionId: 1,
    targetNetProfit: 500,
  });

  assert.equal(request.path, "/api/ops/search-conversion-work-package");
  assert.equal(request.method, "POST");
  assert.equal(request.body.action_id, 1);
  assert.equal(request.body.target_net_profit, 500);
  assert.equal(request.body.metrics.id, 24);
  assert.equal(request.body.product_issue_actions[0].id, 1);
});

test("builds strategy action reconcile requests with dry-run by default", () => {
  const request = buildStrategyActionReconcileRequest({
    latestStrategySnapshotId: 3,
    limit: 200,
    apply: false,
  });

  assert.equal(request.path, "/api/ops/reconcile-strategy-actions");
  assert.equal(request.method, "POST");
  assert.equal(request.body.latest_strategy_snapshot_id, 3);
  assert.equal(request.body.limit, 200);
  assert.equal(request.body.apply, false);
});
