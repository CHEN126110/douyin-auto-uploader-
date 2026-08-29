import { CdpClient, delay, getCdpTargets, normalizeCdpListUrl, withCdpTarget } from "./cdp-client.js";

const DEFAULT_TARGET_HINT = "fxg.jinritemai.com";
const DEFAULT_TEXT_LIMIT = 30000;
export const DEFAULT_SHOP_METRICS_URL = "https://fxg.jinritemai.com/ffa/mshop/homepage/index";

const METRIC_DEFINITIONS = Object.freeze([
  {
    name: "net_profit",
    kind: "money",
    labels: [/经营净利/, /净利润/, /预估净利/, /预计净利/],
    verifiedNetProfit: true,
  },
  {
    name: "gross_sales",
    kind: "money",
    labels: [/成交金额/, /支付金额/, /销售额/, /\bGMV\b/i],
  },
  {
    name: "orders_count",
    kind: "count",
    labels: [/支付订单数/, /成交订单数/, /成交订单/, /订单数/],
  },
  {
    name: "refund_amount",
    kind: "money",
    labels: [/退款金额/, /退款/, /售后退款/],
  },
  {
    name: "after_sale_amount",
    kind: "money",
    labels: [/售后损失/, /售后金额/, /售后/],
  },
  {
    name: "promotion_cost",
    kind: "money",
    labels: [/推广消耗/, /广告消耗/, /推广费/, /营销消耗/, /消耗/],
  },
  {
    name: "experience_score",
    kind: "score",
    labels: [/店铺体验分/, /体验分/],
  },
  {
    name: "product_exposure_count",
    kind: "count",
    labels: [/商品曝光人数/],
  },
  {
    name: "product_click_count",
    kind: "count",
    labels: [/商品点击人数/],
  },
  {
    name: "search_exposure_count",
    kind: "count",
    labels: [/搜索曝光人数/],
  },
]);

function roundMoney(value) {
  return Math.round((Number(value) + Number.EPSILON) * 100) / 100;
}

function splitVisibleLines(text) {
  return String(text || "")
    .replace(/\u00a0/g, " ")
    .split(/\r?\n| {2,}/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean);
}

function hasLabel(line, labels) {
  return labels.some((pattern) => pattern.test(line));
}

function removeLabels(line, labels) {
  let next = String(line || "");
  for (const pattern of labels) {
    next = next.replace(pattern, " ");
  }
  return next;
}

function parseNumberToken(text) {
  const normalized = String(text || "").replace(/,/g, "");
  const match = normalized.match(/[-+]?\d+(?:\.\d+)?/);
  if (!match) return null;
  return Number(match[0]);
}

function parseMoney(text) {
  const source = String(text || "").replace(/,/g, "");
  const match = source.match(/[-+]?\d+(?:\.\d+)?/);
  if (!match) return null;
  let value = Number(match[0]);
  if (!Number.isFinite(value)) return null;
  if (/万|w\b/i.test(source)) {
    value *= 10000;
  }
  return roundMoney(value);
}

function parseCount(text) {
  const value = parseNumberToken(text);
  if (value == null || !Number.isFinite(value)) return null;
  return Math.max(Math.round(value), 0);
}

function parseScore(text) {
  const value = parseNumberToken(text);
  if (value == null || !Number.isFinite(value)) return null;
  if (value < 0 || value > 100) return null;
  return roundMoney(value);
}

function parseMetricValue(text, kind) {
  if (kind === "count") return parseCount(text);
  if (kind === "score") return parseScore(text);
  return parseMoney(text);
}

function findMetric(lines, definition) {
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!hasLabel(line, definition.labels)) continue;

    const candidates = [
      removeLabels(line, definition.labels),
      lines[index + 1],
      lines[index + 2],
      lines[index + 3],
    ].filter(Boolean);

    for (const candidate of candidates) {
      const value = parseMetricValue(candidate, definition.kind);
      if (value == null) continue;
      return {
        value,
        raw: `${line} ${candidate}`.replace(/\s+/g, " ").trim(),
      };
    }
  }
  return null;
}

function parseCountByPatterns(text, patterns) {
  const source = String(text || "");
  for (const pattern of patterns) {
    const match = source.match(pattern);
    if (!match) continue;
    const value = parseCount(match[1] ?? match[0]);
    if (value != null) return value;
  }
  return 0;
}

function findCountNearLabel(lines, labelPattern, lookAhead = 3) {
  for (let index = 0; index < lines.length; index += 1) {
    const line = String(lines[index] || "");
    if (!labelPattern.test(line)) continue;
    const candidates = [];
    for (let offset = 0; offset <= lookAhead; offset += 1) {
      candidates.push(String(lines[index + offset] || ""));
    }
    for (const candidate of candidates) {
      const value = parseCount(candidate.replace(labelPattern, " "));
      if (value != null) return value;
    }
  }
  return 0;
}

function extractOpportunityKeywords(text) {
  const source = String(text || "");
  const keywords = [];
  const labeledMatches = source.matchAll(/(?:机会词(?:包括)?|搜索机会词|机会商品词)[：:\s]*([^\n\r。]+)/g);
  for (const match of labeledMatches) {
    const segment = String(match[1] || "");
    for (const item of segment.split(/[、,，\s]+/)) {
      const keyword = item.trim();
      if (/袜/.test(keyword) && keyword.length >= 2 && keyword.length <= 20 && !keywords.includes(keyword)) {
        keywords.push(keyword);
      }
    }
  }
  return keywords.slice(0, 12);
}

function extractRefundReasons(text) {
  const reasons = {};
  const source = String(text || "");
  const reasonPatterns = [
    /(多拍\/错拍\/不想要|不想要了|其他|与商家协商一致退款)\s*[：:]?\s*(\d+)\s*条/g,
    /(多拍\/错拍\/不想要|不想要了|其他|与商家协商一致退款)[^\d\n\r]{0,12}(\d+)/g,
  ];
  for (const pattern of reasonPatterns) {
    for (const match of source.matchAll(pattern)) {
      const label = String(match[1] || "").trim();
      const count = parseCount(match[2]);
      if (label && count != null && reasons[label] == null) {
        reasons[label] = count;
      }
    }
  }
  return reasons;
}

function isStandaloneNumber(line) {
  return /^\d+(?:\.\d+)?$/.test(String(line || "").trim());
}

function parseProductIssueRows(lines) {
  const idIndexes = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (/^ID[：:]\s*\d{8,}/.test(String(lines[index] || ""))) {
      idIndexes.push(index);
    }
  }

  const products = [];
  for (let pos = 0; pos < idIndexes.length; pos += 1) {
    const idIndex = idIndexes[pos];
    const idLine = String(lines[idIndex] || "");
    const idMatch = idLine.match(/^ID[：:]\s*(\d{8,})/);
    if (!idMatch) continue;

    const title = String(lines[idIndex - 1] || "").trim();
    if (!title || /商品信息|信息质量分|商品问题|近30天销量|操作/.test(title)) continue;

    const nextIdIndex = idIndexes[pos + 1] ?? lines.length;
    const blockEnd = Math.max(idIndex + 1, nextIdIndex - 1);
    const block = lines.slice(idIndex + 1, blockEnd).map((line) => String(line || "").trim()).filter(Boolean);
    const issues = block.filter((line) =>
      /^(商品缺少|商品无达人测评|规格图重复|主图视频|缺少直播讲解回放|缺少规格图)/.test(line)
    );
    if (issues.length === 0) continue;

    const qualityScore = (() => {
      const excellentIndex = block.findIndex((line) => /优秀|及格|不及格/.test(line));
      const candidates = excellentIndex >= 0 ? block.slice(excellentIndex + 1, excellentIndex + 4) : block;
      for (const line of candidates) {
        if (!isStandaloneNumber(line)) continue;
        const value = parseCount(line);
        if (value != null && value >= 0 && value <= 100) return value;
      }
      return 0;
    })();

    const recentSales = (() => {
      const actionIndex = block.findIndex((line) => /立即优化|优化效果/.test(line));
      const candidates = actionIndex >= 0 ? block.slice(0, actionIndex) : block;
      const numbers = candidates
        .filter(isStandaloneNumber)
        .map((line) => parseCount(line))
        .filter((value) => value != null);
      if (numbers.length >= 2) return numbers[numbers.length - 1];
      return 0;
    })();

    products.push({
      title,
      product_id: idMatch[1],
      quality_score: qualityScore,
      recent_30d_sales: recentSales,
      issues,
    });
  }

  return products.slice(0, 50);
}

function isLoginPage(page) {
  const url = String(page.url || "").toLowerCase();
  const title = String(page.title || "");
  const text = String(page.text || "");
  if (/login|passport|sso/.test(url)) return true;
  if (/登录/.test(title) && /扫码|验证码|手机号|账户/.test(text)) return true;
  return /扫码登录|手机号登录|验证码登录|请登录/.test(text);
}

export function parseShopMetricsFromText(page) {
  const url = String(page.url || "");
  const title = String(page.title || "");
  const text = String(page.text || "");
  const lines = splitVisibleLines(text);

  if (!url.includes("jinritemai.com")) {
    return {
      success: false,
      reason: "not_fxg_page",
      metrics: {},
      auditMetrics: [],
      page: { url, title },
    };
  }

  if (isLoginPage({ url, title, text })) {
    return {
      success: false,
      reason: "needs_login",
      metrics: {},
      auditMetrics: [
        {
          metric_name: "cdp_page_state",
          metric_value: "needs_login",
          source: "cdp_browser",
          page_url: url,
          status: "needs_login",
        },
      ],
      page: { url, title },
    };
  }

  const metrics = {
    snapshot_date: new Date().toISOString().slice(0, 10),
    source: "cdp_browser",
  };
  const auditMetrics = [];
  let netProfitVerified = false;

  for (const definition of METRIC_DEFINITIONS) {
    const found = findMetric(lines, definition);
    if (!found) continue;
    metrics[definition.name] = found.value;
    if (definition.verifiedNetProfit) {
      netProfitVerified = true;
    }
    auditMetrics.push({
      metric_name: definition.name,
      metric_value: String(found.value),
      source: "cdp_browser",
      page_url: url,
      status: "observed",
    });
  }

  const metricKeys = Object.keys(metrics).filter((key) => !["snapshot_date", "source"].includes(key));
  metrics.net_profit_verified = netProfitVerified;
  metrics.status = netProfitVerified
    ? "cdp_profit_observed"
    : metricKeys.length > 0
      ? "cdp_partial_no_net_profit"
      : "cdp_observed_no_metrics";
  metrics.notes = netProfitVerified
    ? "CDP 页面读数包含明确经营净利标签。"
    : "CDP 页面读数未包含明确经营净利标签，不能证明已达到日净利目标。";
  metrics.raw_payload = {
    url,
    title,
    line_count: lines.length,
    observed_metric_keys: metricKeys,
    text_excerpt: text.slice(0, 2000),
  };

  return {
    success: metricKeys.length > 0,
    reason: metricKeys.length > 0 ? "metrics_observed" : "no_metrics_observed",
    metrics: metricKeys.length > 0 ? metrics : {},
    auditMetrics,
    page: {
      url,
      title,
      readyState: page.readyState || "",
    },
  };
}

export function parseStrategySignalsFromText(page) {
  const url = String(page.url || "");
  const title = String(page.title || "");
  const text = String(page.text || "");
  const lines = splitVisibleLines(text);

  if (!url.includes("jinritemai.com")) {
    return {
      success: false,
      reason: "not_fxg_page",
      signals: {},
      auditMetrics: [],
      page: { url, title },
    };
  }

  if (isLoginPage({ url, title, text })) {
    return {
      success: false,
      reason: "needs_login",
      signals: {},
      auditMetrics: [
        {
          metric_name: "strategy_page_state",
          metric_value: "needs_login",
          source: "cdp_browser",
          page_url: url,
          status: "needs_login",
        },
      ],
      page: { url, title },
    };
  }

  const joined = lines.join("\n");
  const productCount = findCountNearLabel(lines, /在售商品(?:数)?/);
  const excellentProductCount = findCountNearLabel(lines, /优秀商品(?:数)?/);
  const explicitMissingSpecImageCount = parseCountByPatterns(joined, [
    /缺少规格图\s*(\d+)\s*个/,
    /商品缺少规格图\s*(\d+)\s*个/,
  ]);
  const missingSpecImageCount = explicitMissingSpecImageCount || [...joined.matchAll(/商品缺少规格图/g)].length;
  const signals = {
    product_count: productCount || parseCountByPatterns(joined, [
      /在售商品(?:数)?\s*(\d+)/,
      /在售商品数\s*\n\s*(\d+)/,
    ]),
    excellent_product_count: excellentProductCount || parseCountByPatterns(joined, [
      /优秀商品(?:数)?\s*(\d+)/,
      /优秀商品数\s*\n\s*(\d+)/,
    ]),
    missing_main_video_count: parseCountByPatterns(joined, [
      /(\d+)\s*个商品缺失主图视频/,
      /缺少主图视频\s*(\d+)(?:\s*个)?/,
      /商品缺少主图视频\s*(\d+)(?:\s*个)?/,
      /主图视频(?:质量不合格|待优化)?\s*(\d+)\s*个/,
    ]),
    missing_live_replay_count: parseCountByPatterns(joined, [
      /缺少(?:直播)?讲解回放\s*(\d+)(?:\s*个)?/,
      /讲解回放\s*(\d+)\s*个/,
    ]),
    attribute_optimization_count: parseCountByPatterns(joined, [
      /商品属性优化[：:\s]*(\d+)\s*个/,
      /属性优化[：:\s]*(\d+)\s*个/,
    ]),
    missing_spec_image_count: missingSpecImageCount,
    risk_product_count: parseCountByPatterns(joined, [
      /风险商品\s*(\d+)/,
      /待整改风险点\s*(\d+)/,
    ]),
    opportunity_keywords: extractOpportunityKeywords(joined),
    refund_reasons: extractRefundReasons(joined),
    product_issues: parseProductIssueRows(lines),
    source: "cdp_browser",
    snapshot_date: new Date().toISOString().slice(0, 10),
  };

  const observedKeys = Object.entries(signals)
    .filter(([key, value]) => {
      if (["source", "snapshot_date"].includes(key)) return false;
      if (Array.isArray(value)) return value.length > 0;
      if (value && typeof value === "object") return Object.keys(value).length > 0;
      return Number(value || 0) > 0;
    })
    .map(([key]) => key);
  signals.status = observedKeys.length > 0 ? "strategy_signals_observed" : "no_strategy_signals_observed";
  signals.raw_payload = {
    url,
    title,
    line_count: lines.length,
    observed_signal_keys: observedKeys,
    text_excerpt: text.slice(0, 2000),
  };

  return {
    success: observedKeys.length > 0,
    reason: observedKeys.length > 0 ? "strategy_signals_observed" : "no_strategy_signals_observed",
    signals: observedKeys.length > 0 ? signals : {},
    auditMetrics: observedKeys.map((key) => ({
      metric_name: `strategy_${key}`,
      metric_value: JSON.stringify(signals[key]),
      source: "cdp_browser",
      page_url: url,
      status: "observed",
    })),
    page: {
      url,
      title,
      readyState: page.readyState || "",
    },
  };
}

function browserMetricsExpression(textLimit) {
  const limit = Math.max(1000, Math.min(Number(textLimit || DEFAULT_TEXT_LIMIT), 100000));
  return `(() => {
    const isVisible = (el) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const textOf = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
    const cards = Array.from(document.querySelectorAll("section,article,li,td,th,div,span,p"))
      .filter(isVisible)
      .map(textOf)
      .filter((text) => /(成交|订单|退款|售后|推广|消耗|体验分|净利|GMV|销售额|曝光|点击|搜索)/i.test(text))
      .slice(0, 120);
    return {
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      text: (document.body?.innerText || "").slice(0, ${limit}),
      cards
    };
  })()`;
}

function browserStrategyExpression(textLimit) {
  const limit = Math.max(1000, Math.min(Number(textLimit || DEFAULT_TEXT_LIMIT), 100000));
  return `(() => {
    const isVisible = (el) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const textOf = (el) => (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
    const cards = Array.from(document.querySelectorAll("section,article,li,td,th,div,span,p"))
      .filter(isVisible)
      .map(textOf)
      .filter((text) => /(诊断|质量|缺少|规格图|主图视频|讲解回放|属性优化|风险商品|机会词|退款|错拍|不想要|搜索|袜)/i.test(text))
      .slice(0, 160);
    return {
      url: location.href,
      title: document.title,
      readyState: document.readyState,
      text: (document.body?.innerText || "").slice(0, ${limit}),
      cards
    };
  })()`;
}

export function buildCdpNewTabUrl(cdpListUrl, navigateUrl) {
  const normalized = normalizeCdpListUrl(cdpListUrl);
  const base = normalized.replace(/\/json\/list(?:\?.*)?$/, "/json/new");
  return `${base}?${encodeURIComponent(navigateUrl || DEFAULT_SHOP_METRICS_URL)}`;
}

export function buildCdpCloseTabUrl(cdpListUrl, targetId) {
  const normalized = normalizeCdpListUrl(cdpListUrl);
  return normalized.replace(/\/json\/list(?:\?.*)?$/, `/json/close/${encodeURIComponent(String(targetId || ""))}`);
}

async function fetchJsonText(url, options = {}) {
  const response = await fetch(url, options);
  const rawText = await response.text();
  let payload = {};
  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = { raw: rawText };
    }
  }
  return { ok: response.ok, status: response.status, payload };
}

async function createTemporaryCdpTarget({ cdpListUrl, navigateUrl }) {
  const targetUrl = navigateUrl || DEFAULT_SHOP_METRICS_URL;
  const newTabUrl = buildCdpNewTabUrl(cdpListUrl, targetUrl);
  const created = await fetchJsonText(newTabUrl, { method: "PUT" });
  if (!created.ok) {
    throw new Error(`Failed to create temporary CDP tab: HTTP ${created.status}`);
  }
  let target = created.payload || {};
  if (!target.webSocketDebuggerUrl || !target.id) {
    const deadline = Date.now() + 5000;
    while (Date.now() < deadline) {
      const targets = await getCdpTargets(cdpListUrl);
      const found = targets.find((item) => item.type === "page" && item.url === targetUrl) ||
        targets.find((item) => item.type === "page" && String(item.url || "").includes("/ffa/mshop/homepage"));
      if (found?.webSocketDebuggerUrl && found?.id) {
        target = found;
        break;
      }
      await delay(250);
    }
  }
  if (!target.webSocketDebuggerUrl || !target.id) {
    throw new Error("Temporary CDP tab did not expose a page websocket debugger URL.");
  }
  return target;
}

async function closeTemporaryCdpTarget({ cdpListUrl, targetId, navigateUrl }) {
  if (!targetId) return { attempted: false, ok: false };
  const closeUrl = buildCdpCloseTabUrl(cdpListUrl, targetId);
  try {
    const closed = await fetchJsonText(closeUrl);
    if (closed.ok) {
      return { attempted: true, ok: true, status: closed.status, target_id: targetId };
    }
    if (navigateUrl) {
      const targets = await getCdpTargets(cdpListUrl);
      const fallback = targets.find((item) => (
        item.type === "page" &&
        item.id !== targetId &&
        String(item.url || "") === String(navigateUrl || "")
      ));
      if (fallback?.id) {
        const fallbackClosed = await fetchJsonText(buildCdpCloseTabUrl(cdpListUrl, fallback.id));
        return {
          attempted: true,
          ok: fallbackClosed.ok,
          status: fallbackClosed.status,
          target_id: targetId,
          fallback_target_id: fallback.id,
        };
      }
    }
    return { attempted: true, ok: false, status: closed.status, target_id: targetId };
  } catch (error) {
    return { attempted: true, ok: false, error: String(error?.message || error) };
  }
}

async function evaluateShopMetricsOnTarget(client, target, options = {}) {
  const evaluated = await client.call("Runtime.evaluate", {
    expression: browserMetricsExpression(options.textLimit),
    awaitPromise: true,
    returnByValue: true,
  });
  if (evaluated.exceptionDetails) {
    return {
      success: false,
      reason: "browser_evaluation_failed",
      error: evaluated.exceptionDetails.text || "Runtime.evaluate failed",
      target,
    };
  }
  const page = evaluated.result?.value || {};
  const parsed = parseShopMetricsFromText(page);
  return {
    ...parsed,
    target: {
      id: target.id,
      title: target.title,
      url: target.url,
      temporary: !!options.temporary,
    },
    browser: {
      status: parsed.success ? "ready" : parsed.reason,
      has_browser: true,
      url: page.url || target.url || "",
      title: page.title || target.title || "",
      source: "cdp_browser",
    },
    raw_payload: {
      page: parsed.page,
      cards: Array.isArray(page.cards) ? page.cards.slice(0, 40) : [],
      reason: parsed.reason,
      temporary_tab: options.temporary ? {
        created_target_id: target.id,
        navigate_url: options.navigateUrl || DEFAULT_SHOP_METRICS_URL,
      } : undefined,
    },
  };
}

export async function readShopMetricsViaCdp(options = {}) {
  if (options.useTemporaryTab) {
    return readShopMetricsViaTemporaryCdpTab(options);
  }
  const targetUrlContains = options.targetUrlContains || DEFAULT_TARGET_HINT;
  const cdpListUrl = options.cdpListUrl;
  const result = await withCdpTarget({ cdpListUrl, targetUrlContains }, async (client, target) => {
    return evaluateShopMetricsOnTarget(client, target, options);
  });
  return result;
}

export async function readShopMetricsViaTemporaryCdpTab(options = {}) {
  const cdpListUrl = normalizeCdpListUrl(options.cdpListUrl);
  const navigateUrl = options.navigateUrl || DEFAULT_SHOP_METRICS_URL;
  const createClient = options.clientFactory || ((webSocketDebuggerUrl) => new CdpClient(webSocketDebuggerUrl));
  let target = null;
  let closeResult = { attempted: false, ok: false };
  try {
    target = await createTemporaryCdpTarget({ cdpListUrl, navigateUrl });
    await delay(Number(options.waitMs || 3500));
    const client = createClient(target.webSocketDebuggerUrl);
    await client.connect();
    try {
      return await evaluateShopMetricsOnTarget(client, target, {
        ...options,
        temporary: true,
        navigateUrl,
      });
    } finally {
      client.close();
    }
  } finally {
    if (target?.id) {
      closeResult = await closeTemporaryCdpTarget({ cdpListUrl, targetId: target.id, navigateUrl });
    }
  }
}

async function evaluateStrategySignalsOnTarget(client, target, options = {}) {
  if (options.navigateUrl && !options.temporary) {
    await client.call("Page.navigate", { url: options.navigateUrl });
    await delay(Number(options.waitMs || 2500));
  }
  const evaluated = await client.call("Runtime.evaluate", {
    expression: browserStrategyExpression(options.textLimit),
    awaitPromise: true,
    returnByValue: true,
  });
  if (evaluated.exceptionDetails) {
    return {
      success: false,
      reason: "browser_evaluation_failed",
      error: evaluated.exceptionDetails.text || "Runtime.evaluate failed",
      target,
    };
  }
  const page = evaluated.result?.value || {};
  const parsed = parseStrategySignalsFromText(page);
  return {
    ...parsed,
    target: {
      id: target.id,
      title: target.title,
      url: target.url,
      temporary: !!options.temporary,
    },
    browser: {
      status: parsed.success ? "ready" : parsed.reason,
      has_browser: true,
      url: page.url || target.url || "",
      title: page.title || target.title || "",
      source: "cdp_browser",
    },
    raw_payload: {
      page: parsed.page,
      cards: Array.isArray(page.cards) ? page.cards.slice(0, 60) : [],
      reason: parsed.reason,
      temporary_tab: options.temporary ? {
        created_target_id: target.id,
        navigate_url: options.navigateUrl || "",
      } : undefined,
    },
  };
}

export async function readStrategySignalsViaCdp(options = {}) {
  if (options.useTemporaryTab) {
    return readStrategySignalsViaTemporaryCdpTab(options);
  }
  const targetUrlContains = options.targetUrlContains || DEFAULT_TARGET_HINT;
  const cdpListUrl = options.cdpListUrl;
  const result = await withCdpTarget({ cdpListUrl, targetUrlContains }, async (client, target) => {
    return evaluateStrategySignalsOnTarget(client, target, options);
  });
  return result;
}

export async function readStrategySignalsViaTemporaryCdpTab(options = {}) {
  const cdpListUrl = normalizeCdpListUrl(options.cdpListUrl);
  const navigateUrl = options.navigateUrl || DEFAULT_SHOP_METRICS_URL;
  const createClient = options.clientFactory || ((webSocketDebuggerUrl) => new CdpClient(webSocketDebuggerUrl));
  let target = null;
  let closeResult = { attempted: false, ok: false };
  try {
    target = await createTemporaryCdpTarget({ cdpListUrl, navigateUrl });
    await delay(Number(options.waitMs || 3500));
    const client = createClient(target.webSocketDebuggerUrl);
    await client.connect();
    try {
      return await evaluateStrategySignalsOnTarget(client, target, {
        ...options,
        temporary: true,
        navigateUrl,
      });
    } finally {
      client.close();
    }
  } finally {
    if (target?.id) {
      closeResult = await closeTemporaryCdpTarget({ cdpListUrl, targetId: target.id, navigateUrl });
    }
  }
}
