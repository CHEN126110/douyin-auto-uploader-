import test from "node:test";
import assert from "node:assert/strict";

import { buildNetProfitVerificationMatrixRequest } from "../core.js";

test("builds net profit verification matrix requests with order rows", () => {
  const request = buildNetProfitVerificationMatrixRequest({
    orders: [
      {
        order_id: "order-1",
        sale_price: 20,
        goods_cost: 2,
        shipping_cost: 3,
        packaging_cost: 0.3,
        platform_commission_rate: 0.05,
        promotion_cost: 0,
        refund_loss: 0.2,
        after_sale_loss: 0,
      },
    ],
    targetNetProfit: 500,
  });

  assert.equal(request.path, "/api/ops/net-profit-verification-matrix");
  assert.deepEqual(request.body, {
    orders: [
      {
        order_id: "order-1",
        sale_price: 20,
        goods_cost: 2,
        shipping_cost: 3,
        packaging_cost: 0.3,
        platform_commission_rate: 0.05,
        promotion_cost: 0,
        refund_loss: 0.2,
        after_sale_loss: 0,
      },
    ],
    target_net_profit: 500,
  });
});
