import test from "node:test";
import assert from "node:assert/strict";

import { buildPortfolioPathTo500Request } from "../core.js";

test("builds portfolio path requests with metrics and action rows", () => {
  const request = buildPortfolioPathTo500Request({
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    productIssueActions: [
      {
        id: 3,
        product_id: "3811995393416364123",
        action_status: "in_progress",
      },
    ],
    targetNetProfit: 500,
  });

  assert.equal(request.path, "/api/ops/portfolio-path-to-500");
  assert.deepEqual(request.body, {
    metrics: { id: 22, product_click_count: 3, orders_count: 0 },
    product_issue_actions: [
      {
        id: 3,
        product_id: "3811995393416364123",
        action_status: "in_progress",
      },
    ],
    target_net_profit: 500,
  });
});
