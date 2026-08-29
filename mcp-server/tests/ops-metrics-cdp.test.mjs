import test from "node:test";
import assert from "node:assert/strict";

import {
  buildCdpCloseTabUrl,
  buildCdpNewTabUrl,
  parseShopMetricsFromText,
  parseStrategySignalsFromText,
  readShopMetricsViaCdp,
  readStrategySignalsViaCdp,
} from "../ops-metrics-cdp.js";

test("builds CDP temporary tab endpoints from a json/list URL", () => {
  const listUrl = "http://127.0.0.1:9333/json/list";
  const homepageUrl = "https://fxg.jinritemai.com/ffa/mshop/homepage/index";

  assert.equal(
    buildCdpNewTabUrl(listUrl, homepageUrl),
    `http://127.0.0.1:9333/json/new?${encodeURIComponent(homepageUrl)}`
  );
  assert.equal(
    buildCdpCloseTabUrl(listUrl, "ABC-123"),
    "http://127.0.0.1:9333/json/close/ABC-123"
  );
});

test("reads strategy signals through a temporary CDP tab and closes it", async () => {
  const listUrl = "http://127.0.0.1:9333/json/list";
  const diagnoseUrl = "https://fxg.jinritemai.com/ffa/g/diagnose";
  const expectedNewUrl = buildCdpNewTabUrl(listUrl, diagnoseUrl);
  const expectedCloseUrl = buildCdpCloseTabUrl(listUrl, "TEMP-STRATEGY");
  const fetchCalls = [];
  const clientEvents = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), method: options.method || "GET" });
    if (String(url) === expectedNewUrl) {
      return {
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify({
            id: "TEMP-STRATEGY",
            type: "page",
            url: diagnoseUrl,
            title: "商品诊断",
            webSocketDebuggerUrl: "ws://temporary-strategy",
          }),
      };
    }
    if (String(url) === expectedCloseUrl) {
      return { ok: true, status: 200, text: async () => "{}" };
    }
    return { ok: true, status: 200, text: async () => "[]" };
  };

  const fakeClient = {
    connect: async () => clientEvents.push("connect"),
    call: async (method, params) => {
      clientEvents.push(method);
      assert.equal(method, "Runtime.evaluate");
      assert.match(params.expression, /商品诊断|诊断|质量|缺少/);
      return {
        result: {
          value: {
            url: diagnoseUrl,
            title: "商品诊断",
            readyState: "complete",
            text: ["在售商品数", "22", "商品缺少主图视频 2 个", "风险商品 1"].join("\n"),
            cards: [],
          },
        },
      };
    },
    close: () => clientEvents.push("close"),
  };

  try {
    const result = await readStrategySignalsViaCdp({
      cdpListUrl: listUrl,
      useTemporaryTab: true,
      navigateUrl: diagnoseUrl,
      waitMs: 1,
      textLimit: 5000,
      clientFactory: () => fakeClient,
    });

    assert.equal(result.success, true);
    assert.equal(result.target.temporary, true);
    assert.equal(result.raw_payload.temporary_tab.created_target_id, "TEMP-STRATEGY");
    assert.equal(result.signals.product_count, 22);
    assert.equal(result.signals.missing_main_video_count, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(fetchCalls, [
    { url: expectedNewUrl, method: "PUT" },
    { url: expectedCloseUrl, method: "GET" },
  ]);
  assert.deepEqual(clientEvents, ["connect", "Runtime.evaluate", "close"]);
});

test("closes temporary shop metrics tab by matching URL when primary close fails", async () => {
  const listUrl = "http://127.0.0.1:9333/json/list";
  const homepageUrl = "https://fxg.jinritemai.com/ffa/mshop/homepage/index";
  const expectedNewUrl = buildCdpNewTabUrl(listUrl, homepageUrl);
  const expectedCloseUrl = buildCdpCloseTabUrl(listUrl, "TEMP-SHOP");
  const expectedFallbackCloseUrl = buildCdpCloseTabUrl(listUrl, "TEMP-SHOP-FALLBACK");
  const fetchCalls = [];
  const clientEvents = [];
  const originalFetch = globalThis.fetch;

  globalThis.fetch = async (url, options = {}) => {
    fetchCalls.push({ url: String(url), method: options.method || "GET" });
    if (String(url) === expectedNewUrl) {
      return {
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify({
            id: "TEMP-SHOP",
            type: "page",
            url: homepageUrl,
            title: "首页",
            webSocketDebuggerUrl: "ws://temporary-shop",
          }),
      };
    }
    if (String(url) === expectedCloseUrl) {
      return { ok: false, status: 500, text: async () => "{}" };
    }
    if (String(url) === listUrl) {
      return {
        ok: true,
        status: 200,
        text: async () =>
          JSON.stringify([
            {
              id: "TEMP-SHOP-FALLBACK",
              type: "page",
              url: homepageUrl,
              title: "首页",
              webSocketDebuggerUrl: "ws://temporary-shop-fallback",
            },
          ]),
      };
    }
    if (String(url) === expectedFallbackCloseUrl) {
      return { ok: true, status: 200, text: async () => "{}" };
    }
    return { ok: true, status: 200, text: async () => "[]" };
  };

  const fakeClient = {
    connect: async () => clientEvents.push("connect"),
    call: async (method, params) => {
      clientEvents.push(method);
      assert.equal(method, "Runtime.evaluate");
      assert.match(params.expression, /成交\|订单\|退款/);
      return {
        result: {
          value: {
            url: homepageUrl,
            title: "首页",
            readyState: "complete",
            text: ["经营数据", "成交金额", "0", "成交订单数", "0", "商品曝光人数", "47", "商品点击人数", "3"].join("\n"),
            cards: [],
          },
        },
      };
    },
    close: () => clientEvents.push("close"),
  };

  try {
    const result = await readShopMetricsViaCdp({
      cdpListUrl: listUrl,
      useTemporaryTab: true,
      navigateUrl: homepageUrl,
      waitMs: 1,
      textLimit: 5000,
      clientFactory: () => fakeClient,
    });

    assert.equal(result.success, true);
    assert.equal(result.target.temporary, true);
    assert.equal(result.metrics.orders_count, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(fetchCalls, [
    { url: expectedNewUrl, method: "PUT" },
    { url: expectedCloseUrl, method: "GET" },
    { url: listUrl, method: "GET" },
    { url: expectedFallbackCloseUrl, method: "GET" },
  ]);
  assert.deepEqual(clientEvents, ["connect", "Runtime.evaluate", "close"]);
});

test("parses visible FXG shop metrics from text without inventing net profit", () => {
  const result = parseShopMetricsFromText({
    url: "https://fxg.jinritemai.com/ffa/mshop/dashboard",
    title: "抖店 - 经营概览",
    text: [
      "今日经营概览",
      "成交金额",
      "￥1,234.56",
      "支付订单数",
      "36",
      "退款金额",
      "12.30元",
      "推广消耗",
      "80",
      "店铺体验分",
      "4.72",
      "商品曝光人数",
      "51",
      "商品点击人数",
      "0",
      "搜索曝光人数",
      "251",
    ].join("\n"),
  });

  assert.equal(result.success, true);
  assert.equal(result.metrics.gross_sales, 1234.56);
  assert.equal(result.metrics.orders_count, 36);
  assert.equal(result.metrics.refund_amount, 12.3);
  assert.equal(result.metrics.promotion_cost, 80);
  assert.equal(result.metrics.experience_score, 4.72);
  assert.equal(result.metrics.product_exposure_count, 51);
  assert.equal(result.metrics.product_click_count, 0);
  assert.equal(result.metrics.search_exposure_count, 251);
  assert.equal(result.metrics.net_profit_verified, false);
  assert.equal(result.metrics.status, "cdp_partial_no_net_profit");
});

test("marks net profit as verified only when an explicit net profit label is visible", () => {
  const result = parseShopMetricsFromText({
    url: "https://fxg.jinritemai.com/ffa/mshop/dashboard",
    title: "抖店 - 经营概览",
    text: "经营净利\n¥512.30\n成交金额\n¥900.00",
  });

  assert.equal(result.metrics.net_profit, 512.3);
  assert.equal(result.metrics.net_profit_verified, true);
  assert.equal(result.metrics.status, "cdp_profit_observed");
});

test("does not extract shop metrics from login pages", () => {
  const result = parseShopMetricsFromText({
    url: "https://fxg.jinritemai.com/login",
    title: "抖店登录",
    text: "扫码登录 手机号登录 验证码登录",
  });

  assert.equal(result.success, false);
  assert.equal(result.reason, "needs_login");
  assert.deepEqual(result.metrics, {});
});

test("parses strategy and product diagnostic signals from visible FXG text", () => {
  const result = parseStrategySignalsFromText({
    url: "https://fxg.jinritemai.com/ffa/g/diagnose",
    title: "商品诊断",
    text: [
      "商品信息质量概况",
      "在售商品数",
      "22",
      "优秀商品数",
      "22",
      "质量分重点问题：商品缺少主图视频 6 个",
      "缺少直播讲解回放 22 个",
      "商品属性优化：6 个",
      "商品缺少规格图 3 个",
      "风险商品 12",
      "机会词包括：男士夏薄款袜子、女夏季薄款棉袜、女夏季薄款船袜、女夏季薄款袜套",
      "申请原因 多拍/错拍/不想要 12 条",
    ].join("\n"),
  });

  assert.equal(result.success, true);
  assert.equal(result.signals.product_count, 22);
  assert.equal(result.signals.excellent_product_count, 22);
  assert.equal(result.signals.missing_main_video_count, 6);
  assert.equal(result.signals.missing_live_replay_count, 22);
  assert.equal(result.signals.attribute_optimization_count, 6);
  assert.equal(result.signals.missing_spec_image_count, 3);
  assert.equal(result.signals.risk_product_count, 12);
  assert.deepEqual(result.signals.opportunity_keywords, [
    "男士夏薄款袜子",
    "女夏季薄款棉袜",
    "女夏季薄款船袜",
    "女夏季薄款袜套",
  ]);
  assert.equal(result.signals.refund_reasons["多拍/错拍/不想要"], 12);
  assert.equal(result.signals.status, "strategy_signals_observed");
});

test("does not treat ordinary product titles as opportunity keywords", () => {
  const result = parseStrategySignalsFromText({
    url: "https://fxg.jinritemai.com/ffa/mshop/homepage/index",
    title: "首页",
    text: [
      "短视频挂新品 提曝光 +3",
      "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜",
      "美蕾丝花边棉袜堆堆袜,木耳边蝴蝶结袜子女中筒袜春夏季款棉袜韩版日系学院风少女长筒袜",
      "风险商品 12",
    ].join("\n"),
  });

  assert.equal(result.success, true);
  assert.equal(result.signals.risk_product_count, 12);
  assert.deepEqual(result.signals.opportunity_keywords, []);
});

test("parses actual product diagnosis page count formats", () => {
  const result = parseStrategySignalsFromText({
    url: "https://fxg.jinritemai.com/ffa/g/diagnose",
    title: "商品诊断",
    text: [
      "在售商品数",
      "22",
      "优秀商品数",
      "请继续保持",
      "22",
      "优化主图视频最高提升5分",
      "6个商品缺失主图视频",
      "重点问题",
      "商品缺少主图视频 6",
      "缺少直播讲解回放 22",
      "推荐问题：",
      "商品缺少讲解回放",
      "商品缺少规格图",
      "推荐问题：",
      "商品缺少讲解回放",
      "商品缺少规格图",
      "规格图重复",
    ].join("\n"),
  });

  assert.equal(result.signals.product_count, 22);
  assert.equal(result.signals.excellent_product_count, 22);
  assert.equal(result.signals.missing_main_video_count, 6);
  assert.equal(result.signals.missing_live_replay_count, 22);
  assert.equal(result.signals.missing_spec_image_count, 2);
});

test("extracts concrete product issue rows from diagnosis text", () => {
  const result = parseStrategySignalsFromText({
    url: "https://fxg.jinritemai.com/ffa/g/diagnose",
    title: "商品诊断",
    text: [
      "商品信息",
      "信息质量分",
      "商品问题",
      "近30天销量",
      "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
      "ID：3819238447663677663",
      "优秀",
      "90",
      "推荐问题：",
      "商品缺少主图视频或主图视频质量不合格",
      "商品无达人测评",
      "商品缺少讲解回放",
      "7",
      "立即优化",
      "songmu淞木 布标镂空无骨袜子女春夏新品薄款中筒袜韩系ins堆堆",
      "ID：3811600816893198348",
      "优秀",
      "90",
      "推荐问题：",
      "商品缺少规格图",
      "商品缺少讲解回放",
      "5",
      "立即优化",
    ].join("\n"),
  });

  assert.equal(result.signals.product_issues.length, 2);
  assert.deepEqual(result.signals.product_issues[0], {
    title: "韩系波点中筒袜防臭夏天袜子白女夏季薄款甜美蕾丝花边棉袜堆堆袜",
    product_id: "3819238447663677663",
    quality_score: 90,
    recent_30d_sales: 7,
    issues: [
      "商品缺少主图视频或主图视频质量不合格",
      "商品无达人测评",
      "商品缺少讲解回放",
    ],
  });
  assert.equal(result.signals.product_issues[1].recent_30d_sales, 5);
  assert.equal(result.signals.product_issues[1].issues[0], "商品缺少规格图");
});
