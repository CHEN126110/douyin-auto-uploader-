import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import * as z from "zod/v4";
import { registerCdpTools } from "./cdp-tools.js";
import { readShopMetricsViaCdp, readStrategySignalsViaCdp } from "./ops-metrics-cdp.js";

export const DEFAULT_BACKEND_URL = "http://127.0.0.1:5001";

const CATEGORY_OPTIONS = Object.freeze([
  { value: 0, label: "船袜", aliases: ["船袜", "浅口袜", "隐形袜", "boat", "invisible"] },
  { value: 1, label: "短袜", aliases: ["短袜", "短筒袜", "short"] },
  { value: 2, label: "中筒袜", aliases: ["中筒袜", "中袜", "crew", "mid"] },
  { value: 3, label: "长筒袜", aliases: ["长筒袜", "长袜", "knee", "long"] },
  { value: 4, label: "袜套", aliases: ["袜套", "leg warmer", "cover"] },
]);

const IMAGE_EXTENSIONS = new Set([
  ".jpg",
  ".jpeg",
  ".png",
  ".webp",
  ".bmp",
  ".gif",
]);

const VIDEO_EXTENSIONS = new Set([
  ".mp4",
  ".mov",
  ".avi",
  ".mkv",
  ".webm",
  ".m4v",
]);

const DEFAULT_PRICING_CONFIG = Object.freeze({
  target_gross_margin: 30,
});

const DEFAULT_COST_ITEMS = Object.freeze([
  { name: "运费", cost_type: "fixed", value: 3 },
  { name: "包装费", cost_type: "fixed", value: 0.5 },
  { name: "平台佣金", cost_type: "percentage", value: 5 },
]);

const QuantityOverrideSchema = z
  .object({
    skuPath: z.string().min(1).optional().describe("Absolute SKU image path for an exact match."),
    skuName: z
      .string()
      .min(1)
      .optional()
      .describe("SKU display name. Only safe when that name is unique within the product."),
    quantity: z.number().int().positive().describe("Resolved pair count for this SKU."),
    note: z
      .string()
      .optional()
      .describe("Optional note explaining why this quantity override is correct."),
  })
  .refine((value) => Boolean(value.skuPath || value.skuName), {
    message: "Provide either skuPath or skuName for each quantity override.",
    path: ["skuPath"],
  });

function getBackendBaseUrl() {
  return process.env.DOUYIN_BACKEND_URL || DEFAULT_BACKEND_URL;
}

class BackendError extends Error {
  constructor(message, context = {}) {
    super(message);
    this.name = "BackendError";
    this.status = context.status ?? null;
    this.url = context.url ?? null;
    this.details = context.details ?? null;
  }
}

function hasOwn(object, key) {
  return Object.prototype.hasOwnProperty.call(object, key);
}

function pruneUndefined(object) {
  for (const key of Object.keys(object)) {
    if (object[key] === undefined) {
      delete object[key];
    }
  }
  return object;
}

function buildUrl(path, query = {}) {
  const url = new URL(path, getBackendBaseUrl());
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    url.searchParams.set(key, String(value));
  }
  return url;
}

async function parseResponseBody(response) {
  const rawText = await response.text();
  if (!rawText) {
    return {};
  }

  try {
    return JSON.parse(rawText);
  } catch {
    return { raw: rawText };
  }
}

async function backendRequest(path, options = {}) {
  const { method = "GET", query, body } = options;
  const url = buildUrl(path, query);

  let response;
  try {
    response = await fetch(url, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    throw new BackendError(
      `Unable to reach Douyin backend at ${url}. Make sure the Tauri app or sidecar is running.`,
      {
        url: url.toString(),
        details: error instanceof Error ? error.message : String(error),
      }
    );
  }

  const payload = await parseResponseBody(response);

  if (!response.ok) {
    throw new BackendError(
      payload?.msg ||
        payload?.message ||
        `Backend request failed with HTTP ${response.status}.`,
      {
        status: response.status,
        url: url.toString(),
        details: payload,
      }
    );
  }

  if (payload && typeof payload === "object" && payload.success === false) {
    throw new BackendError(payload.msg || payload.message || "Backend returned an error.", {
      status: response.status,
      url: url.toString(),
      details: payload,
    });
  }

  return payload;
}

export function buildUploadStartRequest({
  recordId,
  allProducts,
  stopBeforeSubmit,
  confirmFinalPublish,
} = {}) {
  if (recordId && allProducts) {
    throw new Error("Provide either recordId or allProducts=true, not both.");
  }
  if (!recordId && !allProducts) {
    throw new Error("Provide recordId for a single product upload, or allProducts=true.");
  }

  const resolvedStopBeforeSubmit =
    stopBeforeSubmit === undefined ? true : Boolean(stopBeforeSubmit);
  const finalPublishConfirmed = Boolean(confirmFinalPublish);

  if (!resolvedStopBeforeSubmit && !finalPublishConfirmed) {
    throw new Error(
      "Final publish requires confirmFinalPublish=true when stopBeforeSubmit=false."
    );
  }

  const stopBody = {
    stop_before_submit: resolvedStopBeforeSubmit,
  };

  if (!resolvedStopBeforeSubmit && finalPublishConfirmed) {
    stopBody.confirm_final_publish = true;
  }

  if (allProducts) {
    return {
      path: "/api/upload/start-all",
      body: stopBody,
    };
  }

  return {
    path: "/api/upload/start",
    body: {
      record_id: recordId,
      ...stopBody,
    },
  };
}

export function buildPostSaveConversionMonitorRequest({
  metrics,
  action,
  actionId,
  saveGate,
  conversionExperimentPlan,
  targetNetProfit,
  savedConfirmed,
} = {}) {
  const body = {
    metrics,
    action,
    action_id: actionId,
    save_gate: saveGate,
    conversion_experiment_plan: conversionExperimentPlan,
    target_net_profit: targetNetProfit,
    saved_confirmed: savedConfirmed,
  };
  return {
    path: "/api/ops/post-save-conversion-monitor",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildProfitLadderTo500Request({
  metrics,
  product,
  costScenarios,
  targetNetProfit,
} = {}) {
  const body = {
    metrics,
    product,
    cost_scenarios: costScenarios,
    target_net_profit: targetNetProfit,
  };
  return {
    path: "/api/ops/profit-ladder-to-500",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildConversionAssetPackRequest({
  metrics,
  product,
  detailAudit,
  pageSnapshot,
  suggestions,
  targetNetProfit,
} = {}) {
  const body = {
    metrics,
    product,
    detail_audit: detailAudit,
    page_snapshot: pageSnapshot,
    suggestions,
    target_net_profit: targetNetProfit,
  };
  return {
    path: "/api/ops/conversion-asset-pack",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildPortfolioPathTo500Request({
  metrics,
  productIssueActions,
  targetNetProfit,
  limit,
  actionStatus,
} = {}) {
  const body = {
    metrics,
    product_issue_actions: productIssueActions,
    target_net_profit: targetNetProfit,
    limit,
    action_status: actionStatus,
  };
  return {
    path: "/api/ops/portfolio-path-to-500",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildSearchConversionWorkPackageRequest({
  metrics,
  productIssueActions,
  actionId,
  targetNetProfit,
  limit,
} = {}) {
  const body = {
    metrics,
    product_issue_actions: productIssueActions,
    action_id: actionId,
    target_net_profit: targetNetProfit,
    limit,
  };
  return {
    path: "/api/ops/search-conversion-work-package",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildStrategyActionReconcileRequest({
  productIssueActions,
  latestStrategySnapshotId,
  limit,
  apply,
} = {}) {
  const body = {
    product_issue_actions: productIssueActions,
    latest_strategy_snapshot_id: latestStrategySnapshotId,
    limit,
    apply,
  };
  return {
    path: "/api/ops/reconcile-strategy-actions",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildFirstOrderDecisionMatrixRequest({
  baselineMetrics,
  currentMetrics,
  metrics,
  action,
  actionId,
  saveGate,
  targetNetProfit,
  savedConfirmed,
} = {}) {
  const body = {
    baseline_metrics: baselineMetrics,
    current_metrics: currentMetrics,
    metrics,
    action,
    action_id: actionId,
    save_gate: saveGate,
    target_net_profit: targetNetProfit,
    saved_confirmed: savedConfirmed,
  };
  return {
    path: "/api/ops/first-order-decision-matrix",
    method: "POST",
    body: pruneUndefined(body),
  };
}

export function buildNetProfitVerificationMatrixRequest({
  orders,
  targetNetProfit,
} = {}) {
  const body = {
    orders,
    target_net_profit: targetNetProfit,
  };
  return {
    path: "/api/ops/net-profit-verification-matrix",
    method: "POST",
    body: pruneUndefined(body),
  };
}

function jsonText(payload) {
  return JSON.stringify(payload, null, 2);
}

function jsonResult(payload) {
  return {
    content: [{ type: "text", text: jsonText(payload) }],
    structuredContent: payload,
  };
}

function extractCaptureTaskId(payload) {
  const nestedTaskId = payload?.data?.task_id;
  if (typeof nestedTaskId === "string" && nestedTaskId.trim()) {
    return nestedTaskId.trim();
  }

  const topLevelTaskId = payload?.task_id;
  if (typeof topLevelTaskId === "string" && topLevelTaskId.trim()) {
    return topLevelTaskId.trim();
  }

  return null;
}

function normalizeCaptureResponse(payload) {
  const taskId = extractCaptureTaskId(payload);
  if (!taskId) {
    return payload;
  }

  return {
    ...payload,
    task_id: taskId,
    data: {
      ...(payload?.data ?? {}),
      task_id: taskId,
      url: payload?.data?.url ?? payload?.url ?? null,
    },
  };
}

function errorResult(error) {
  const normalized =
    error instanceof BackendError
      ? error
      : new BackendError(error instanceof Error ? error.message : String(error));

  const payload = {
    success: false,
    error: normalized.message,
    status: normalized.status,
    url: normalized.url,
    details: normalized.details,
  };

  return {
    isError: true,
    content: [{ type: "text", text: jsonText(payload) }],
    structuredContent: payload,
  };
}

async function fetchProductDetail(recordId, loadImages = false) {
  const payload = await backendRequest("/load_detail", {
    query: {
      _id: recordId,
      images: loadImages ? "true" : "false",
    },
  });
  return normalizeProductDetailPayload(payload);
}

const KNOWN_PRODUCT_ASSET_DIR_NAMES = new Set([
  "sku",
  "主图",
  "详情页",
  "详情",
  "3:4",
  "3：4",
  "34",
  "主图3:4",
  "主图3：4",
  "主图34",
]);

function computeCommonDirectory(paths) {
  const resolvedPaths = paths.map((value) => path.resolve(String(value)));
  if (!resolvedPaths.length) {
    return null;
  }

  const parsed = resolvedPaths.map((value) => ({
    root: path.parse(value).root,
    segments: value.slice(path.parse(value).root.length).split(path.sep).filter(Boolean),
  }));

  const root = parsed[0].root;
  if (parsed.some((item) => item.root !== root)) {
    return null;
  }

  const commonSegments = [];
  const shortestLength = Math.min(...parsed.map((item) => item.segments.length));
  for (let index = 0; index < shortestLength; index += 1) {
    const segment = parsed[0].segments[index];
    if (parsed.every((item) => item.segments[index] === segment)) {
      commonSegments.push(segment);
    } else {
      break;
    }
  }

  if (!commonSegments.length) {
    return root || null;
  }

  return path.join(root, ...commonSegments);
}

function deriveProductRootPathFromSkus(detail) {
  const skuPaths = Array.isArray(detail?.content)
    ? detail.content
        .map((sku) => (typeof sku?.path === "string" ? sku.path.trim() : ""))
        .filter(Boolean)
    : [];

  if (!skuPaths.length) {
    return null;
  }

  const skuDirectories = skuPaths.map((skuPath) => path.dirname(path.resolve(skuPath)));
  let candidate = computeCommonDirectory(skuDirectories) || skuDirectories[0];
  const basename = path.basename(candidate).toLowerCase();
  if (KNOWN_PRODUCT_ASSET_DIR_NAMES.has(basename)) {
    candidate = path.dirname(candidate);
  }

  return candidate || null;
}

function normalizeProductDetailPayload(payload) {
  if (!payload?.data || typeof payload.data !== "object") {
    return payload;
  }

  const detail = payload.data;
  if (!detail.path) {
    const derivedRootPath = deriveProductRootPathFromSkus(detail);
    if (derivedRootPath) {
      detail.path = derivedRootPath;
    }
  }

  return payload;
}

function toNumberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeSkuName(value) {
  return String(value ?? "").trim().replace(/\s+/g, " ").toLowerCase();
}

function normalizeLookupText(value) {
  return String(value ?? "")
    .trim()
    .replace(/[\s_\-:：/\\]+/g, "")
    .toLowerCase();
}

function getCategoryOptions() {
  return CATEGORY_OPTIONS.map(({ value, label }) => ({ value, label }));
}

function resolveCategoryOption({ categoryValue, categoryLabel } = {}) {
  if (categoryValue !== undefined && categoryValue !== null) {
    const byValue = CATEGORY_OPTIONS.find((item) => item.value === Number(categoryValue));
    if (!byValue) {
      throw new Error(`Unknown category value: ${categoryValue}`);
    }
    return { value: byValue.value, label: byValue.label };
  }

  if (categoryLabel !== undefined && categoryLabel !== null) {
    const needle = normalizeLookupText(categoryLabel);
    const byLabel = CATEGORY_OPTIONS.find((item) =>
      item.aliases.some((alias) => normalizeLookupText(alias) === needle)
    );
    if (!byLabel) {
      throw new Error(`Unknown category label: ${categoryLabel}`);
    }
    return { value: byLabel.value, label: byLabel.label };
  }

  throw new Error("Provide either categoryValue or categoryLabel.");
}

function normalizePathKey(value) {
  const resolved = path.resolve(String(value ?? ""));
  return process.platform === "win32" ? resolved.toLowerCase() : resolved;
}

async function statPath(targetPath) {
  try {
    return await fs.stat(targetPath);
  } catch {
    return null;
  }
}

function toIsoString(dateLike) {
  if (!dateLike) {
    return null;
  }
  try {
    return new Date(dateLike).toISOString();
  } catch {
    return null;
  }
}

function safeRelativePath(rootPath, absolutePath) {
  const relativePath = path.relative(rootPath, absolutePath);
  if (!relativePath || relativePath === "") {
    return ".";
  }
  return relativePath.startsWith("..") ? null : relativePath;
}

async function collectDirectoryEntries(rootPath, options = {}) {
  const {
    maxDepth = 4,
    includeDirectories = false,
    includeFiles = true,
    allowedExtensions = null,
  } = options;

  const entries = [];
  const normalizedMaxDepth = Math.max(0, Number(maxDepth) || 0);

  async function walk(currentPath, depth) {
    let dirents;
    try {
      dirents = await fs.readdir(currentPath, { withFileTypes: true });
    } catch {
      return;
    }

    dirents.sort((left, right) => left.name.localeCompare(right.name, "zh-CN"));

    for (const dirent of dirents) {
      const absolutePath = path.join(currentPath, dirent.name);
      const relativePath = safeRelativePath(rootPath, absolutePath);
      if (!relativePath) {
        continue;
      }

      if (dirent.isDirectory()) {
        if (includeDirectories) {
          const stat = await statPath(absolutePath);
          entries.push({
            kind: "directory",
            name: dirent.name,
            relative_path: relativePath,
            absolute_path: absolutePath,
            size: stat?.size ?? null,
            modified_at: toIsoString(stat?.mtime),
          });
        }

        if (depth < normalizedMaxDepth) {
          await walk(absolutePath, depth + 1);
        }
        continue;
      }

      if (!includeFiles) {
        continue;
      }

      const extension = path.extname(dirent.name).toLowerCase();
      if (allowedExtensions && !allowedExtensions.has(extension)) {
        continue;
      }

      const stat = await statPath(absolutePath);
      entries.push({
        kind: "file",
        name: dirent.name,
        relative_path: relativePath,
        absolute_path: absolutePath,
        extension,
        size: stat?.size ?? null,
        modified_at: toIsoString(stat?.mtime),
      });
    }
  }

  await walk(rootPath, 0);
  return entries;
}

function classifyAsset(relativePath, absolutePath, skuPathKeys) {
  const normalizedRelative = String(relativePath ?? "")
    .replace(/\\/g, "/")
    .toLowerCase();
  const normalizedAbsolute = normalizePathKey(absolutePath);
  const extension = path.extname(absolutePath).toLowerCase();

  if (VIDEO_EXTENSIONS.has(extension)) {
    return "videos";
  }

  if (!IMAGE_EXTENSIONS.has(extension)) {
    return "other_files";
  }

  if (skuPathKeys.has(normalizedAbsolute)) {
    return "sku_images";
  }

  if (
    normalizedRelative.includes("3:4") ||
    normalizedRelative.includes("3：4") ||
    normalizedRelative.includes("3-4") ||
    normalizedRelative.includes("3_4") ||
    normalizedRelative.includes("3比4")
  ) {
    return "main_images_3_4";
  }

  if (normalizedRelative.includes("白底") || normalizedRelative.includes("white")) {
    return "white_background_images";
  }

  if (normalizedRelative.includes("详情") || normalizedRelative.includes("detail")) {
    return "detail_images";
  }

  if (normalizedRelative.includes("主图") || normalizedRelative.includes("main")) {
    return "main_images";
  }

  return "other_media";
}

function summarizeProduct(detail) {
  const skuCount = Array.isArray(detail?.content) ? detail.content.length : 0;
  return {
    id: detail?.id ?? null,
    name: detail?.name ?? null,
    title: detail?.title ?? "",
    clazz: detail?.clazz ?? null,
    remark: detail?.remark ?? "",
    repo: detail?.repo ?? null,
    sku_count: skuCount,
    path: detail?.path ?? null,
  };
}

function isIdModeProduct(product) {
  const name = String(product?.name ?? "").trim();
  if (/^ID-\d+$/iu.test(name)) {
    return true;
  }

  const productPath = String(product?.path ?? "").replace(/\\/g, "/").toLowerCase();
  return /\/uploads\/products\/id-\d+/u.test(productPath);
}

function analyzeProductDetail(detail) {
  const skus = Array.isArray(detail?.content) ? detail.content : [];
  const duplicateBuckets = new Map();
  const missingSkuNames = [];
  const missingSkuPrices = [];
  const invalidSkuPrices = [];

  for (const sku of skus) {
    const path = sku?.path ?? "";
    const name = String(sku?.name ?? "").trim();
    const normalizedName = normalizeSkuName(name);

    if (!name) {
      missingSkuNames.push({ path, name });
    } else {
      const bucket = duplicateBuckets.get(normalizedName) ?? {
        normalized_name: normalizedName,
        display_name: name,
        paths: [],
      };
      bucket.paths.push(path);
      duplicateBuckets.set(normalizedName, bucket);
    }

    const priceNumber = toNumberOrNull(sku?.price);
    if (sku?.price === "" || sku?.price === null || sku?.price === undefined) {
      missingSkuPrices.push({ path, name });
    } else if (priceNumber === null || priceNumber <= 0) {
      invalidSkuPrices.push({
        path,
        name,
        raw_price: sku?.price,
      });
    }
  }

  const duplicateSkuNameGroups = Array.from(duplicateBuckets.values())
    .filter((bucket) => bucket.paths.length > 1)
    .map((bucket) => ({
      normalized_name: bucket.normalized_name,
      display_name: bucket.display_name,
      count: bucket.paths.length,
      paths: bucket.paths,
    }));

  const titlePresent = Boolean(String(detail?.title ?? "").trim());
  const categoryPresent =
    detail?.clazz !== null &&
    detail?.clazz !== undefined &&
    String(detail?.clazz).trim() !== "";
  const skuCount = skus.length;

  const issues = [];

  if (!titlePresent) {
    issues.push({ code: "missing_title", severity: "error", message: "Product title is empty." });
  }

  if (!categoryPresent) {
    issues.push({ code: "missing_category", severity: "error", message: "Product category is missing." });
  }

  if (skuCount === 0) {
    issues.push({ code: "missing_skus", severity: "error", message: "Product has no SKU records." });
  }

  if (missingSkuNames.length > 0) {
    issues.push({
      code: "missing_sku_names",
      severity: "error",
      message: `${missingSkuNames.length} SKU entries are missing names.`,
      items: missingSkuNames,
    });
  }

  if (missingSkuPrices.length > 0) {
    issues.push({
      code: "missing_sku_prices",
      severity: "error",
      message: `${missingSkuPrices.length} SKU entries are missing prices.`,
      items: missingSkuPrices,
    });
  }

  if (invalidSkuPrices.length > 0) {
    issues.push({
      code: "invalid_sku_prices",
      severity: "error",
      message: `${invalidSkuPrices.length} SKU entries have invalid or non-positive prices.`,
      items: invalidSkuPrices,
    });
  }

  if (duplicateSkuNameGroups.length > 0) {
    issues.push({
      code: "duplicate_sku_names",
      severity: "error",
      message: `Found ${duplicateSkuNameGroups.length} duplicate SKU name groups.`,
      items: duplicateSkuNameGroups,
    });
  }

  const ready =
    issues.every((issue) => issue.severity !== "error") &&
    titlePresent &&
    categoryPresent &&
    skuCount > 0;

  const nextActions = [];
  if (!titlePresent) nextActions.push("Generate or set a product title.");
  if (!categoryPresent) nextActions.push("Set the product category before upload.");
  if (missingSkuNames.length > 0) nextActions.push("Fill in missing SKU names.");
  if (missingSkuPrices.length > 0 || invalidSkuPrices.length > 0) {
    nextActions.push("Fill in valid positive prices for every SKU.");
  }
  if (duplicateSkuNameGroups.length > 0) {
    nextActions.push("Rename duplicate SKU names so every SKU name is unique.");
  }
  if (ready) nextActions.push("Product is ready to upload.");

  return {
    ready,
    product: summarizeProduct(detail),
    checks: {
      title_present: titlePresent,
      category_present: categoryPresent,
      sku_count: skuCount,
      missing_sku_name_count: missingSkuNames.length,
      missing_sku_price_count: missingSkuPrices.length,
      invalid_sku_price_count: invalidSkuPrices.length,
      duplicate_sku_name_group_count: duplicateSkuNameGroups.length,
    },
    issues,
    duplicate_sku_name_groups: duplicateSkuNameGroups,
    next_actions: nextActions,
  };
}

function mergeUploadReadiness(productValidation, assetValidation) {
  const nextActions = Array.from(
    new Set([...(productValidation?.next_actions || []), ...(assetValidation?.next_actions || [])])
  );

  return {
    ready: Boolean(productValidation?.ready) && Boolean(assetValidation?.ready),
    product: productValidation?.product ?? assetValidation?.manifest?.product ?? null,
    checks: {
      ...(productValidation?.checks || {}),
      assets_ready: Boolean(assetValidation?.ready),
      asset_issue_count: Array.isArray(assetValidation?.issues) ? assetValidation.issues.length : 0,
      ...(assetValidation?.checks || {}),
    },
    issues: [...(productValidation?.issues || []), ...(assetValidation?.issues || [])],
    duplicate_sku_name_groups: productValidation?.duplicate_sku_name_groups || [],
    next_actions: nextActions,
    product_validation: productValidation,
    asset_validation: assetValidation,
  };
}

function mergeSkuUpdates(currentSkus, skuUpdates = []) {
  const updatesByPath = new Map();

  for (const update of skuUpdates) {
    if (updatesByPath.has(update.path)) {
      throw new Error(`Duplicate sku update path: ${update.path}`);
    }
    updatesByPath.set(update.path, update);
  }

  const seenPaths = new Set();
  const merged = currentSkus.map((sku) => {
    const update = updatesByPath.get(sku.path);
    if (!update) {
      return { ...sku };
    }

    seenPaths.add(update.path);
    return {
      ...sku,
      name: hasOwn(update, "name") && update.name != null ? update.name : sku.name,
      price: hasOwn(update, "price") && update.price != null ? update.price : sku.price,
    };
  });

  for (const path of updatesByPath.keys()) {
    if (!seenPaths.has(path)) {
      throw new Error(`SKU path not found on product: ${path}`);
    }
  }

  return merged;
}

function buildSavePayload(recordId, detail, updates, mergedSkus) {
  const payload = {
    _id: recordId,
    title: hasOwn(updates, "title") ? updates.title ?? "" : detail.title ?? "",
    remark: hasOwn(updates, "remark") ? updates.remark ?? "" : detail.remark ?? "",
    repo: hasOwn(updates, "repo") ? updates.repo : detail.repo,
    clazz: hasOwn(updates, "clazz") ? updates.clazz : detail.clazz,
    attr_size: mergedSkus.length,
  };

  mergedSkus.forEach((sku, index) => {
    const number = index + 1;
    payload[`attr_path_${number}`] = sku.path;
    payload[`attr_name_${number}`] = sku.name;
    payload[`attr_price_${number}`] = sku.price ?? "";
  });

  return payload;
}

async function persistProductChanges(recordId, updates) {
  const detailResponse = await fetchProductDetail(recordId, false);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const mergedSkus = mergeSkuUpdates(detail.content || [], updates.skuUpdates || []);
  const payload = buildSavePayload(recordId, detail, updates, mergedSkus);

  const saveResponse = await backendRequest("/save_info", {
    method: "POST",
    body: payload,
  });
  const refreshed = await fetchProductDetail(recordId, false);

  return {
    save: saveResponse,
    product: refreshed?.data ?? null,
  };
}

async function deleteSku(recordId, skuPath) {
  const response = await backendRequest("/delete_sku", {
    method: "POST",
    body: {
      record_id: recordId,
      sku_path: skuPath,
    },
  });
  const refreshed = await fetchProductDetail(recordId, false);

  return {
    delete: response,
    product: refreshed?.data ?? null,
  };
}

async function deleteProduct(recordId) {
  const response = await backendRequest("/menu_delete", {
    query: { _id: recordId },
  });
  const products = await backendRequest("/api/products");

  return {
    delete: response,
    products,
  };
}

async function deleteAllProducts() {
  const response = await backendRequest("/delete_all", {
    method: "DELETE",
  });
  const products = await backendRequest("/api/products");

  return {
    delete: response,
    products,
  };
}

async function openProductFolder(recordId) {
  const detailResponse = await fetchProductDetail(recordId, false);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const openResponse = await backendRequest("/menu_open", {
    query: { _id: recordId },
  });

  return {
    open: openResponse,
    product: summarizeProduct(detail),
  };
}

async function updateSettings(settings) {
  const saveResponse = await backendRequest("/settings", {
    method: "POST",
    body: settings,
  });
  const refreshed = await backendRequest("/settings");

  return {
    save: saveResponse,
    settings: refreshed?.data?.settings ?? null,
  };
}

async function resetSettings() {
  const resetResponse = await backendRequest("/settings/reset", {
    method: "POST",
  });
  const refreshed = await backendRequest("/settings");

  return {
    reset: resetResponse,
    settings: refreshed?.data?.settings ?? null,
  };
}

async function listProductFiles(recordId, options = {}) {
  const { maxDepth = 4, mediaOnly = false, includeDirectories = true } = options;
  const detailResponse = await fetchProductDetail(recordId, false);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const rootPath = detail?.path ? path.resolve(detail.path) : null;
  if (!rootPath) {
    return {
      product: summarizeProduct(detail),
      root_path: null,
      exists: false,
      entries: [],
      counts: {
        files: 0,
        directories: 0,
      },
    };
  }

  const rootStat = await statPath(rootPath);
  if (!rootStat?.isDirectory()) {
    return {
      product: summarizeProduct(detail),
      root_path: rootPath,
      exists: false,
      entries: [],
      counts: {
        files: 0,
        directories: 0,
      },
    };
  }

  const allowedExtensions = mediaOnly
    ? new Set([...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS])
    : null;
  const entries = await collectDirectoryEntries(rootPath, {
    maxDepth,
    includeDirectories,
    includeFiles: true,
    allowedExtensions,
  });

  return {
    product: summarizeProduct(detail),
    root_path: rootPath,
    exists: true,
    entries,
    counts: {
      files: entries.filter((entry) => entry.kind === "file").length,
      directories: entries.filter((entry) => entry.kind === "directory").length,
    },
  };
}

async function listSkuAssets(recordId, options = {}) {
  const { includeBase64 = false } = options;
  const detailResponse = await fetchProductDetail(recordId, includeBase64);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const rootPath = detail?.path ? path.resolve(detail.path) : null;
  const skus = Array.isArray(detail?.content) ? detail.content : [];
  const skuAssets = [];

  for (const [index, sku] of skus.entries()) {
    const absolutePath = sku?.path ? path.resolve(sku.path) : null;
    const fileStat = absolutePath ? await statPath(absolutePath) : null;
    skuAssets.push({
      index: index + 1,
      sku_name: sku?.name ?? "",
      file_name: sku?.file_name ?? "",
      dir_name: sku?.dir_name ?? "",
      price: sku?.price ?? "",
      absolute_path: absolutePath,
      relative_path:
        rootPath && absolutePath ? safeRelativePath(rootPath, absolutePath) : null,
      exists: Boolean(fileStat?.isFile()),
      size: fileStat?.size ?? null,
      modified_at: toIsoString(fileStat?.mtime),
      image_base64: includeBase64 ? sku?.url ?? null : null,
    });
  }

  return {
    product: summarizeProduct(detail),
    root_path: rootPath,
    sku_count: skuAssets.length,
    skus: skuAssets,
  };
}

async function buildProductAssetManifest(recordId, options = {}) {
  const { maxDepth = 4 } = options;
  const detailResponse = await fetchProductDetail(recordId, false);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const rootPath = detail?.path ? path.resolve(detail.path) : null;
  const rootStat = rootPath ? await statPath(rootPath) : null;
  const rootExists = Boolean(rootStat?.isDirectory());
  const skuList = Array.isArray(detail?.content) ? detail.content : [];
  const skuPathKeys = new Set(
    skuList
      .map((sku) => sku?.path)
      .filter(Boolean)
      .map((skuPath) => normalizePathKey(skuPath))
  );

  const assetGroups = {
    sku_images: [],
    main_images: [],
    main_images_3_4: [],
    detail_images: [],
    white_background_images: [],
    videos: [],
    other_media: [],
    other_files: [],
  };

  for (const sku of skuList) {
    const skuPath = sku?.path ? path.resolve(sku.path) : null;
    const skuStat = skuPath ? await statPath(skuPath) : null;
    assetGroups.sku_images.push({
      sku_name: sku?.name ?? "",
      path: skuPath,
      exists: Boolean(skuStat?.isFile()),
      relative_path:
        rootPath && skuPath ? safeRelativePath(rootPath, skuPath) : null,
      size: skuStat?.size ?? null,
      modified_at: toIsoString(skuStat?.mtime),
    });
  }

  if (rootExists) {
    const mediaEntries = await collectDirectoryEntries(rootPath, {
      maxDepth,
      includeDirectories: false,
      includeFiles: true,
      allowedExtensions: new Set([...IMAGE_EXTENSIONS, ...VIDEO_EXTENSIONS]),
    });

    for (const entry of mediaEntries) {
      const bucket = classifyAsset(entry.relative_path, entry.absolute_path, skuPathKeys);
      if (bucket === "sku_images") {
        continue;
      }
      assetGroups[bucket].push(entry);
    }
  }

  const counts = Object.fromEntries(
    Object.entries(assetGroups).map(([key, value]) => [key, value.length])
  );

  return {
    product: summarizeProduct(detail),
    root_path: rootPath,
    root_exists: rootExists,
    counts,
    assets: assetGroups,
  };
}

async function validateProductAssets(recordId, options = {}) {
  const manifest = await buildProductAssetManifest(recordId, options);
  const missingSkuImages = manifest.assets.sku_images.filter((item) => !item.exists);
  const issues = [];
  const idModeProduct = isIdModeProduct(manifest.product);

  if (!manifest.root_exists) {
    issues.push({
      code: "missing_product_directory",
      severity: "error",
      message: "The product folder does not exist on disk.",
    });
  }

  if (missingSkuImages.length > 0) {
    issues.push({
      code: "missing_sku_images",
      severity: "error",
      message: `${missingSkuImages.length} SKU image files are missing on disk.`,
      items: missingSkuImages,
    });
  }

  if (manifest.counts.main_images === 0) {
    issues.push({
      code: "missing_main_images",
      severity: "error",
      message: "No main images were found in the product folder.",
    });
  }

  if (manifest.counts.main_images_3_4 === 0 && !idModeProduct) {
    issues.push({
      code: "missing_main_images_3_4",
      severity: "error",
      message: "No 3:4 main images were found in the product folder.",
    });
  }

  if (manifest.counts.detail_images === 0) {
    issues.push({
      code: "missing_detail_images",
      severity: "error",
      message: "No detail images were found in the product folder.",
    });
  }

  const ready = issues.length === 0;
  const nextActions = [];
  if (!manifest.root_exists) nextActions.push("Restore or re-import the product folder.");
  if (missingSkuImages.length > 0) nextActions.push("Restore every missing SKU image file.");
  if (manifest.counts.main_images === 0) nextActions.push("Add at least one main image.");
  if (manifest.counts.main_images_3_4 === 0 && !idModeProduct) {
    nextActions.push("Add at least one 3:4 main image.");
  }
  if (manifest.counts.main_images_3_4 === 0 && idModeProduct) {
    nextActions.push("ID 模式当前缺少单独 3:4 主图；上传时将使用平台自带的 1:1 主图一键填入流程。");
  }
  if (manifest.counts.detail_images === 0) nextActions.push("Add at least one detail image.");
  if (ready) nextActions.push("Local product assets look ready for upload.");

  return {
    ready,
    checks: {
      root_exists: manifest.root_exists,
      sku_image_count: manifest.counts.sku_images,
      missing_sku_image_count: missingSkuImages.length,
      main_image_count: manifest.counts.main_images,
      main_image_3_4_count: manifest.counts.main_images_3_4,
      detail_image_count: manifest.counts.detail_images,
      video_count: manifest.counts.videos,
      white_background_image_count: manifest.counts.white_background_images,
    },
    issues,
    next_actions: nextActions,
    manifest,
  };
}

async function buildUploadReadiness(recordId, detail = null, assetValidation = null) {
  const resolvedDetail = detail ?? (await fetchProductDetail(recordId, false))?.data;
  if (!resolvedDetail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const resolvedAssetValidation = assetValidation ?? (await validateProductAssets(recordId));
  return mergeUploadReadiness(analyzeProductDetail(resolvedDetail), resolvedAssetValidation);
}

async function fetchTitleSuggestions(recordId, options = {}) {
  const { enhanced = true, useTrending = true } = options;
  return backendRequest(
    enhanced ? "/api/generate_smart_title_enhanced" : "/api/generate_smart_title",
    {
      method: "POST",
      body: enhanced
        ? { record_id: recordId, use_trending: useTrending }
        : { record_id: recordId },
    }
  );
}

async function fetchSmartPrices(recordId, unitPrice) {
  return backendRequest("/api/pricing/calculate_smart_prices", {
    method: "POST",
    body: {
      record_id: recordId,
      unit_price: unitPrice,
    },
  });
}

async function fetchPricingSettings() {
  const response = await backendRequest("/settings");
  const settings = response?.data?.settings ?? {};
  const pricingConfig =
    settings?.pricing_config && typeof settings.pricing_config === "object"
      ? settings.pricing_config
      : DEFAULT_PRICING_CONFIG;
  const costItems =
    Array.isArray(settings?.cost_items) && settings.cost_items.length > 0
      ? settings.cost_items
      : DEFAULT_COST_ITEMS;

  return {
    settings,
    pricingConfig,
    costItems,
  };
}

function roundToMarketingPrice(price, ensureMinimum = true, tolerance = 0.1) {
  if (!Number.isFinite(price) || price <= 0) {
    return 0.9;
  }

  const intPart = Math.trunc(price);
  const candidates = [];

  if (price < 100) {
    candidates.push(intPart + 0.8, intPart + 0.9, intPart + 1 + 0.8, intPart + 1 + 0.9);
    if (intPart > 0) {
      candidates.push(intPart - 1 + 0.9);
    }
  } else {
    const tens = Math.trunc(price / 10);
    candidates.push(tens * 10 + 9.8, tens * 10 + 9.9, (tens + 1) * 10 + 9.8, (tens + 1) * 10 + 9.9);
    if (tens > 10) {
      candidates.push((tens - 1) * 10 + 9.9);
    }
  }

  const dedupedCandidates = [...new Set(candidates.filter((candidate) => candidate > 0))].sort(
    (left, right) => left - right
  );

  if (ensureMinimum) {
    const minAcceptable = price - tolerance;
    const validCandidates = dedupedCandidates.filter((candidate) => candidate >= minAcceptable);
    if (validCandidates.length > 0) {
      return validCandidates.reduce((best, candidate) =>
        Math.abs(candidate - price) < Math.abs(best - price) ? candidate : best
      );
    }
    if (price < 100) {
      return intPart + 1 + 0.9;
    }
    return (Math.trunc(price / 10) + 1) * 10 + 9.9;
  }

  return dedupedCandidates.reduce((best, candidate) =>
    Math.abs(candidate - price) < Math.abs(best - price) ? candidate : best
  );
}

function normalizeTargetMargin(pricingConfig = {}) {
  const rawMargin = pricingConfig?.target_gross_margin ?? pricingConfig?.target_profit_margin ?? 30;
  const marginValue = Number(rawMargin);
  if (!Number.isFinite(marginValue)) {
    return 0.3;
  }
  return marginValue > 1 ? marginValue / 100 : marginValue;
}

function summarizeCostItems(costItems = []) {
  let fixedCosts = 0;
  let perUnitCostRate = 0;
  let percentageCosts = 0;

  for (const item of costItems) {
    const itemType = item?.cost_type ?? "fixed";
    const itemValue = Number(item?.value ?? 0);
    if (!Number.isFinite(itemValue)) {
      continue;
    }

    if (itemType === "fixed") {
      fixedCosts += itemValue;
    } else if (itemType === "per_unit") {
      perUnitCostRate += itemValue;
    } else if (itemType === "percentage") {
      percentageCosts += itemValue / 100;
    }
  }

  return {
    fixedCosts,
    perUnitCostRate,
    percentageCosts,
  };
}

function pickTitleSuggestion(titleResponse, titleIndex = 0) {
  const suggestions = titleResponse?.data?.suggestions || [];
  if (suggestions.length === 0) {
    return null;
  }

  const normalizedIndex = Math.min(
    Math.max(Number(titleIndex) || 0, 0),
    suggestions.length - 1
  );

  return {
    index: normalizedIndex,
    suggestion: suggestions[normalizedIndex],
    total: suggestions.length,
  };
}

function buildSkuPathIndex(detail) {
  const uniquePathByName = new Map();
  const duplicateNames = new Set();
  const skus = Array.isArray(detail?.content) ? detail.content : [];

  for (const sku of skus) {
    const normalizedName = normalizeSkuName(sku?.name);
    const skuPath = String(sku?.path ?? "").trim();
    if (!normalizedName || !skuPath) {
      continue;
    }

    if (uniquePathByName.has(normalizedName)) {
      duplicateNames.add(normalizedName);
      continue;
    }

    uniquePathByName.set(normalizedName, skuPath);
  }

  for (const duplicateName of duplicateNames) {
    uniquePathByName.delete(duplicateName);
  }

  return uniquePathByName;
}

function buildRuleQuantityIndex(pricingResponse, detail) {
  const pathByName = buildSkuPathIndex(detail);
  const items = pricingResponse?.data?.pricing_results || [];
  const byPath = new Map();

  for (const item of items) {
    const resolvedPath =
      (typeof item?.sku_path === "string" && item.sku_path.trim()) ||
      pathByName.get(normalizeSkuName(item?.sku_name));
    if (!resolvedPath) {
      continue;
    }
    byPath.set(normalizePathKey(resolvedPath), item);
  }

  return byPath;
}

function resolveQuantityOverrides(detail, quantityOverrides = []) {
  const pathByName = buildSkuPathIndex(detail);
  const resolved = new Map();
  const unresolved = [];

  for (const override of quantityOverrides) {
    const quantity = Number(override?.quantity);
    if (!Number.isInteger(quantity) || quantity <= 0) {
      unresolved.push({
        skuPath: override?.skuPath ?? null,
        skuName: override?.skuName ?? null,
        reason: "Quantity must be a positive integer.",
      });
      continue;
    }

    const directPath =
      typeof override?.skuPath === "string" && override.skuPath.trim()
        ? override.skuPath.trim()
        : null;
    const resolvedPath =
      directPath ||
      pathByName.get(normalizeSkuName(override?.skuName));

    if (!resolvedPath) {
      unresolved.push({
        skuPath: override?.skuPath ?? null,
        skuName: override?.skuName ?? null,
        reason:
          "Override could not be matched. Use skuPath for duplicated names or when the name is not unique.",
      });
      continue;
    }

    resolved.set(normalizePathKey(resolvedPath), {
      path: resolvedPath,
      quantity,
      note: override?.note ?? null,
      skuName: override?.skuName ?? null,
    });
  }

  return { resolved, unresolved };
}

function buildPricingPayload(detail, unitPrice, pricingConfig, costItems, rulePricingResponse, quantityOverrides = []) {
  const targetGrossMargin = normalizeTargetMargin(pricingConfig);
  const { fixedCosts, perUnitCostRate, percentageCosts } = summarizeCostItems(costItems);
  const resolvedUnitPrice = Number(unitPrice);
  const skus = Array.isArray(detail?.content) ? detail.content : [];
  const ruleByPath = buildRuleQuantityIndex(rulePricingResponse, detail);
  const { resolved: overrideByPath, unresolved } = resolveQuantityOverrides(detail, quantityOverrides);

  if (unresolved.length > 0) {
    throw new Error(`Some quantity overrides could not be resolved: ${JSON.stringify(unresolved)}`);
  }

  const pricingResults = [];
  let totalPrice = 0;
  let totalMargin = 0;
  let totalRawPrice = 0;

  for (const sku of skus) {
    const skuName = String(sku?.name ?? "");
    const skuPath = String(sku?.path ?? "");
    const pathKey = normalizePathKey(skuPath);
    const override = overrideByPath.get(pathKey) ?? null;
    const ruleItem = ruleByPath.get(pathKey) ?? null;
    const quantity = override?.quantity ?? Number(ruleItem?.quantity ?? 1);

    const sockCost = resolvedUnitPrice * quantity;
    const perUnitExtra = perUnitCostRate * quantity;
    const baseTotalCost = sockCost + fixedCosts + perUnitExtra;

    let denominator = 1 - targetGrossMargin - percentageCosts;
    if (denominator <= 0) {
      denominator = 0.1;
    }

    const rawSuggestedPrice = baseTotalCost / denominator;
    const suggestedPrice = roundToMarketingPrice(rawSuggestedPrice, true);
    const percentageCostAmount = suggestedPrice * percentageCosts;
    const totalCost = baseTotalCost + percentageCostAmount;
    const profit = suggestedPrice - totalCost;
    const profitMargin = suggestedPrice > 0 ? (profit / suggestedPrice) * 100 : 0;
    const isManualOverride = Boolean(override);

    pricingResults.push({
      sku_name: skuName,
      sku_path: skuPath,
      quantity,
      sock_cost: Number(sockCost.toFixed(2)),
      fixed_costs: Number(fixedCosts.toFixed(2)),
      per_unit_extra: Number(perUnitExtra.toFixed(2)),
      percentage_cost: Number(percentageCostAmount.toFixed(2)),
      total_cost: Number(totalCost.toFixed(2)),
      raw_price: Number(rawSuggestedPrice.toFixed(2)),
      suggested_price: Number(suggestedPrice.toFixed(2)),
      profit: Number(profit.toFixed(2)),
      profit_margin: Number(profitMargin.toFixed(1)),
      confidence: isManualOverride ? 1 : Number(ruleItem?.confidence ?? 0.5),
      method: isManualOverride
        ? `manual override${override?.note ? `: ${override.note}` : ""}`
        : String(ruleItem?.method ?? "default"),
      quantity_source: isManualOverride ? "manual_override" : "rule_extractor",
    });

    totalPrice += suggestedPrice;
    totalMargin += profitMargin;
    totalRawPrice += rawSuggestedPrice;
  }

  const count = pricingResults.length;
  const averagePrice = count > 0 ? totalPrice / count : 0;
  const averageMargin = count > 0 ? totalMargin / count : 0;
  const averageRawPrice = count > 0 ? totalRawPrice / count : 0;

  return {
    success: true,
    data: {
      pricing_results: pricingResults,
      statistics: {
        total_skus: count,
        average_price: Number(averagePrice.toFixed(2)),
        average_raw_price: Number(averageRawPrice.toFixed(2)),
        price_adjustment: Number((averagePrice - averageRawPrice).toFixed(2)),
        target_margin: Number((targetGrossMargin * 100).toFixed(1)),
        average_margin: Number(averageMargin.toFixed(1)),
        margin_bonus: Number((averageMargin - targetGrossMargin * 100).toFixed(1)),
        min_price: count > 0 ? Number(Math.min(...pricingResults.map((item) => item.suggested_price)).toFixed(2)) : 0,
        max_price: count > 0 ? Number(Math.max(...pricingResults.map((item) => item.suggested_price)).toFixed(2)) : 0,
      },
      config_used: {
        target_gross_margin: Number((targetGrossMargin * 100).toFixed(1)),
        fixed_costs: Number(fixedCosts.toFixed(2)),
        percentage_costs: Number((percentageCosts * 100).toFixed(1)),
        cost_items_count: Array.isArray(costItems) ? costItems.length : 0,
        marketing_price_enabled: true,
        quantity_override_count: overrideByPath.size,
        quantity_mode: overrideByPath.size > 0 ? "hybrid" : "rule_only",
      },
      quantity_overrides_applied: Array.from(overrideByPath.values()).map((item) => ({
        sku_path: item.path,
        sku_name: item.skuName ?? null,
        quantity: item.quantity,
        note: item.note,
      })),
    },
  };
}

async function getSmartPricingPayload(recordId, unitPrice, options = {}) {
  const quantityOverrides = Array.isArray(options?.quantityOverrides) ? options.quantityOverrides : [];
  if (quantityOverrides.length === 0) {
    return fetchSmartPrices(recordId, unitPrice);
  }

  const [detailResponse, settings, rulePricingResponse] = await Promise.all([
    fetchProductDetail(recordId, false),
    fetchPricingSettings(),
    fetchSmartPrices(recordId, unitPrice),
  ]);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  return buildPricingPayload(
    detail,
    unitPrice,
    settings.pricingConfig,
    settings.costItems,
    rulePricingResponse,
    quantityOverrides
  );
}

async function analyzeSkuQuantities(recordId, options = {}) {
  const { includeBase64 = false } = options;
  const [detailResponse, skuAssets, pricingResponse] = await Promise.all([
    fetchProductDetail(recordId, false),
    listSkuAssets(recordId, { includeBase64 }),
    fetchSmartPrices(recordId, 1),
  ]);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const assetsByPath = new Map(
    (skuAssets?.skus || [])
      .filter((item) => typeof item?.absolute_path === "string" && item.absolute_path.trim())
      .map((item) => [normalizePathKey(item.absolute_path), item])
  );
  const pricingItems = pricingResponse?.data?.pricing_results || [];
  const results = pricingItems.map((item) => {
    const resolvedPath = String(item?.sku_path ?? "");
    const asset = assetsByPath.get(normalizePathKey(resolvedPath)) ?? null;
    const methodText = String(item?.method ?? "");
    const confidence = Number(item?.confidence ?? 0);
    const reviewSuggested =
      confidence < 0.9 || /组合|默认|default/i.test(methodText);

    return {
      sku_name: item?.sku_name ?? "",
      sku_path: resolvedPath,
      inferred_quantity: Number(item?.quantity ?? 1),
      confidence,
      method: methodText,
      review_suggested: reviewSuggested,
      image_path: asset?.absolute_path ?? null,
      image_base64: includeBase64 ? asset?.image_base64 ?? null : null,
      dir_name: asset?.dir_name ?? "",
      file_name: asset?.file_name ?? "",
    };
  });

  return {
    product: summarizeProduct(detail),
    sku_count: results.length,
    review_needed_count: results.filter((item) => item.review_suggested).length,
    results,
  };
}

async function startCaptureBatch(urls, options = {}) {
  const {
    captureOptions = {},
    stopOnError = false,
  } = options;
  const normalizedUrls = [...new Set((urls || []).map((item) => String(item ?? "").trim()).filter(Boolean))];
  const tasks = [];

  for (const url of normalizedUrls) {
    try {
      const response = normalizeCaptureResponse(await backendRequest("/api/capture/start", {
        method: "POST",
        body: { url, options: captureOptions },
      }));
      tasks.push({
        url,
        success: true,
        task_id: extractCaptureTaskId(response),
        response,
      });
    } catch (error) {
      const normalized =
        error instanceof BackendError
          ? error
          : new BackendError(error instanceof Error ? error.message : String(error));
      tasks.push({
        url,
        success: false,
        error: normalized.message,
        details: normalized.details ?? null,
      });
      if (stopOnError) {
        break;
      }
    }
  }

  return {
    requested_count: urls.length,
    unique_url_count: normalizedUrls.length,
    started_count: tasks.filter((item) => item.success).length,
    failed_count: tasks.filter((item) => !item.success).length,
    stop_on_error: stopOnError,
    tasks,
  };
}

function buildPriceSkuUpdates(pricingResponse, detail) {
  const pricingResults = pricingResponse?.data?.pricing_results || [];
  const pathByName = buildSkuPathIndex(detail);
  return pricingResults
    .map((item) => ({
      path:
        (typeof item?.sku_path === "string" && item.sku_path.trim()) ||
        pathByName.get(normalizeSkuName(item?.sku_name)),
      price: item?.suggested_price,
    }))
    .filter(
      (item) =>
        typeof item.path === "string" &&
        item.path.trim() &&
        typeof item.price === "number" &&
        Number.isFinite(item.price)
    )
    .map((item) => ({
      path: item.path,
      price: item.price,
    }));
}

function simulatePreparedDetail(detail, updates) {
  const mergedSkus = mergeSkuUpdates(detail.content || [], updates.skuUpdates || []);
  return {
    ...detail,
    title: hasOwn(updates, "title") ? updates.title ?? "" : detail.title,
    remark: hasOwn(updates, "remark") ? updates.remark ?? "" : detail.remark,
    repo: hasOwn(updates, "repo") ? updates.repo : detail.repo,
    clazz: hasOwn(updates, "clazz") ? updates.clazz : detail.clazz,
    content: mergedSkus,
  };
}

async function buildPreparationDraft(recordId, unitPrice, options = {}) {
  const {
    enhanced = true,
    useTrending = true,
    titleIndex = 0,
    quantityOverrides = [],
  } = options;

  const detailResponse = await fetchProductDetail(recordId, false);
  const detail = detailResponse?.data;
  if (!detail) {
    throw new Error(`Product ${recordId} was not found.`);
  }

  const [titleResponse, pricingResponse, assetValidation] = await Promise.all([
    fetchTitleSuggestions(recordId, { enhanced, useTrending }),
    getSmartPricingPayload(recordId, unitPrice, { quantityOverrides }),
    validateProductAssets(recordId),
  ]);

  const chosenTitle = pickTitleSuggestion(titleResponse, titleIndex);
  const priceSkuUpdates = buildPriceSkuUpdates(pricingResponse, detail);

  const draftUpdates = {
    title: chosenTitle?.suggestion?.title ?? null,
    skuUpdates: priceSkuUpdates,
  };

  const simulatedDetail = simulatePreparedDetail(detail, draftUpdates);

  return {
    product: summarizeProduct(detail),
    current_validation: mergeUploadReadiness(analyzeProductDetail(detail), assetValidation),
    title_generation: {
      enhanced,
      use_trending: useTrending,
      selected_index: chosenTitle?.index ?? null,
      selected_title: chosenTitle?.suggestion?.title ?? null,
      suggestions: titleResponse?.data?.suggestions || [],
      trending_keywords: titleResponse?.data?.trending_keywords || [],
    },
    pricing: {
      unit_price: unitPrice,
      results: pricingResponse?.data?.pricing_results || [],
      statistics: pricingResponse?.data?.statistics || {},
      config_used: pricingResponse?.data?.config_used || {},
      quantity_overrides_applied: pricingResponse?.data?.quantity_overrides_applied || [],
    },
    draft_updates: {
      title: draftUpdates.title,
      sku_update_count: draftUpdates.skuUpdates.length,
      sku_updates: draftUpdates.skuUpdates,
    },
    post_apply_validation: mergeUploadReadiness(analyzeProductDetail(simulatedDetail), assetValidation),
  };
}

function registerTool(server, name, config, handler) {
  server.registerTool(name, config, async (args) => {
    try {
      return jsonResult(await handler(args));
    } catch (error) {
      return errorResult(error);
    }
  });
}

function registerJsonResource(server, name, uri, description, path, options = {}) {
  server.registerResource(
    name,
    uri,
    {
      title: name,
      description,
      mimeType: "application/json",
    },
    async () => {
      const payload = await backendRequest(path, options);
      return {
        contents: [
          {
            uri,
            mimeType: "application/json",
            text: jsonText(payload),
          },
        ],
      };
    }
  );
}

function registerResources(server) {
  registerJsonResource(
    server,
    "backend-health",
    "douyin://health",
    "Current backend health snapshot.",
    "/health"
  );
  registerJsonResource(
    server,
    "products",
    "douyin://products",
    "Current product list from the local database.",
    "/api/products"
  );
  registerJsonResource(
    server,
    "settings",
    "douyin://settings",
    "Current pricing, model, and automation settings.",
    "/settings"
  );
  registerJsonResource(
    server,
    "upload-tasks",
    "douyin://upload/tasks",
    "Current upload task list and browser automation state.",
    "/api/upload/tasks"
  );
}

function registerPrompts(server) {
  server.registerPrompt(
    "prepare-product-for-upload",
    {
      description:
        "Guide the model through reviewing a product, generating title and prices, and checking upload readiness before any mutation.",
      argsSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z.number().positive().describe("Base cost per pair of socks."),
      },
    },
    async ({ recordId, unitPrice }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Prepare product ${recordId} for upload. First call health_check, ` +
              `then use prepare_product_draft with unitPrice=${unitPrice}. ` +
              `Review current_validation and post_apply_validation, explain any blockers, ` +
              `and do not mutate data unless the user asks to apply the draft.`,
          },
        },
      ],
    })
  );

  server.registerPrompt(
    "fix-upload-blockers",
    {
      description:
        "Guide the model through turning upload blockers into concrete fixes before any upload is started.",
      argsSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z
          .number()
          .positive()
          .optional()
          .describe("Base cost per pair of socks when pricing may need to be generated."),
      },
    },
    async ({ recordId, unitPrice }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Repair upload blockers for product ${recordId}. ` +
              `Start with validate_product_for_upload. ` +
              `If the product is missing title or prices and unitPrice is available, use prepare_product_draft` +
              `${unitPrice ? ` with unitPrice=${unitPrice}` : ""} to inspect proposed fixes. ` +
              `If SKU pair counts look ambiguous, use analyze_sku_quantities and build quantityOverrides before pricing. ` +
              `Use apply_preparation_draft only if the user wants automatic title and price updates. ` +
              `Use list_category_options and set_product_category for missing category. ` +
              `Use validate_product_assets, get_product_asset_manifest, list_product_files, list_sku_assets, or open_product_folder for missing asset blockers. ` +
              `Report what was fixed, what still blocks upload, and do not start upload unless the user explicitly asks.`,
          },
        },
      ],
    })
  );

  server.registerPrompt(
    "review-sku-quantities",
    {
      description:
        "Guide the model to inspect SKU names and images, decide the correct pair counts, and use quantity overrides for pricing when the rule extractor may be wrong.",
      argsSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z.number().positive().describe("Base cost per pair of socks."),
      },
    },
    async ({ recordId, unitPrice }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Review SKU quantities for product ${recordId}. ` +
              `Start with analyze_sku_quantities and list_sku_assets. ` +
              `If the inferred quantity for any SKU looks wrong from the SKU text or image, build quantityOverrides using skuPath and the corrected quantity. ` +
              `Then call calculate_smart_prices with unitPrice=${unitPrice} and those quantityOverrides. ` +
              `Only apply prices with apply_preparation_draft if the user wants the changes persisted.`,
          },
        },
      ],
    })
  );

  server.registerPrompt(
    "upload-product-safely",
    {
      description:
        "Guide the model to validate upload readiness before starting an upload task.",
      argsSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
      },
    },
    async ({ recordId }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Validate product ${recordId} with validate_product_for_upload. ` +
              `If blockers remain, report them clearly and stop. ` +
              `If the product is ready and the user wants a safe preflight, use start_validated_upload with stopBeforeSubmit=true and then poll get_upload_status. ` +
              `Do not request final publish/submit unless the user explicitly confirms that irreversible action.`,
          },
        },
      ],
    })
  );

  server.registerPrompt(
    "monitor-upload-task",
    {
      description:
        "Guide the model to monitor one upload task until a terminal state and summarize the result.",
      argsSchema: {
        taskId: z.string().min(1).describe("Upload task ID."),
      },
    },
    async ({ taskId }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Monitor upload task ${taskId}. ` +
              `Poll get_upload_status until it reaches success, failed, or cancelled. ` +
              `Summarize the final state, last progress message, and any error text. ` +
              `If it fails, recommend the next MCP tools to inspect or repair the problem.`,
          },
        },
      ],
    })
  );

  server.registerPrompt(
    "capture-multiple-products",
    {
      description:
        "Guide the model to start capture tasks for multiple source links, track them, and import completed results.",
      argsSchema: {
        urls: z.array(z.string().url()).min(1).describe("Source product links to capture."),
      },
    },
    async ({ urls }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Capture ${urls.length} products from source links. ` +
              `Start with health_check, then call start_capture_batch with the provided URLs. ` +
              `Track each task with get_capture_status, import completed tasks with import_capture_result, and summarize which URLs succeeded, failed, or still need attention.`,
          },
        },
      ],
    })
  );
}

function registerCoreTools(server) {
  registerTool(
    server,
    "health_check",
    {
      description:
        "Check whether the local Douyin publisher backend is running and which modules are available.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/health")
  );

  registerTool(
    server,
    "debug_browser_ensure",
    {
      description:
        "Ensure the shared Douyin browser session exists. Optionally launch the browser, start a new debug session, or navigate to a specific URL.",
      inputSchema: {
        label: z.string().optional().describe("Optional label for the debug session."),
        mode: z.enum(["managed", "attach"]).optional().describe("How to handle the debug browser session."),
        newSession: z.boolean().optional().describe("Create a fresh debug session before continuing."),
        createBrowser: z.boolean().optional().describe("Launch the browser if it is not already running."),
        debugAddress: z.string().optional().describe("Debugger address for attaching to an existing browser, for example 127.0.0.1:9333."),
        existingOnly: z.boolean().optional().describe("Only attach to an existing browser without creating one."),
        navigate: z.boolean().optional().describe("Navigate the current tab to the provided URL."),
        url: z.string().url().optional().describe("Optional URL to open in the current debug tab."),
        includeHtml: z.boolean().optional().describe("Include a short HTML excerpt in the returned snapshot."),
        limit: z.number().int().min(1).max(20).optional().describe("How many visible fields/controls to summarize."),
      },
    },
    async ({
      label,
      mode,
      newSession,
      createBrowser,
      debugAddress,
      existingOnly,
      navigate,
      url,
      includeHtml,
      limit,
    }) =>
      backendRequest("/api/debug/browser/ensure", {
        method: "POST",
        body: {
          label,
          mode,
          new_session: newSession ?? false,
          create_browser: createBrowser ?? true,
          debug_address: debugAddress,
          existing_only: existingOnly,
          navigate: navigate ?? false,
          url,
          include_html: includeHtml ?? false,
          limit: limit ?? 5,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_discover",
    {
      description:
        "Discover browsers that can be attached to for debugging without creating a new session.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        verify: z.boolean().optional().describe("Verify each discovered debugger endpoint through /json/version."),
      },
    },
    async ({ verify }) =>
      backendRequest("/api/debug/browser/discover", {
        query: {
          verify: verify ?? true,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_launch",
    {
      description:
        "Launch a dedicated debug browser with a remote debugging port, then attach the shared browser handle to it.",
      inputSchema: {
        label: z.string().optional().describe("Optional label for the debug session."),
        newSession: z.boolean().optional().describe("Create a fresh debug session before launching."),
        browserPath: z.string().optional().describe("Optional absolute browser executable path."),
        profileName: z.string().optional().describe("Profile name used to create or reuse a dedicated debug browser data directory."),
        userDataDir: z.string().optional().describe("Optional absolute user data directory for the launched debug browser."),
        port: z.number().int().min(1).max(65535).optional().describe("Preferred remote debugging port."),
        url: z.string().url().optional().describe("Optional URL to open after launch or attach."),
        navigate: z.boolean().optional().describe("Navigate the attached tab to the provided URL after launch."),
        reuseExisting: z.boolean().optional().describe("Reuse an existing debug browser on the same port when available."),
        timeout: z.number().min(1).max(30).optional().describe("How many seconds to wait for the debugger endpoint to become ready."),
        includeHtml: z.boolean().optional().describe("Include a short HTML excerpt in the returned snapshot."),
        limit: z.number().int().min(1).max(20).optional().describe("How many visible fields/controls to summarize."),
      },
    },
    async ({
      label,
      newSession,
      browserPath,
      profileName,
      userDataDir,
      port,
      url,
      navigate,
      reuseExisting,
      timeout,
      includeHtml,
      limit,
    }) =>
      backendRequest("/api/debug/browser/launch", {
        method: "POST",
        body: {
          label,
          new_session: newSession ?? false,
          browser_path: browserPath,
          profile_name: profileName,
          user_data_dir: userDataDir,
          port,
          url,
          navigate,
          reuse_existing: reuseExisting ?? true,
          timeout,
          include_html: includeHtml ?? false,
          limit: limit ?? 5,
        },
      })
  );

  registerTool(
    server,
    "get_browser_debug_session",
    {
      description:
        "Read the current browser debug session, including recent debug events and the latest error report if one exists.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/debug/browser/session")
  );

  registerTool(
    server,
    "debug_browser_snapshot",
    {
      description:
        "Inspect the current browser page without mutating it. Returns URL, title, visible attr-field-id sections, visible controls, and optional locator matches.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        locator: z.string().optional().describe("Optional locator to query on the current page."),
        locatorType: z
          .enum(["raw", "css", "xpath"])
          .optional()
          .describe("How to interpret locator. raw accepts DrissionPage locators such as xpath://..."),
        includeHtml: z.boolean().optional().describe("Include a short HTML excerpt in the snapshot."),
        limit: z.number().int().min(1).max(20).optional().describe("Maximum number of locator matches to include."),
      },
    },
    async ({ locator, locatorType, includeHtml, limit }) =>
      backendRequest("/api/debug/browser/context", {
        query: {
          locator,
          locator_type: locatorType ?? "raw",
          include_html: includeHtml ?? false,
          limit: limit ?? 5,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_find_elements",
    {
      description:
        "Query the current browser page for matching elements. Useful after hover/click actions when dynamic popovers or menus appear.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        locator: z.string().min(1).describe("Locator to search for on the current page."),
        locatorType: z
          .enum(["raw", "css", "xpath"])
          .optional()
          .describe("How to interpret locator. raw accepts DrissionPage locators."),
        timeout: z.number().min(0.1).max(5).optional().describe("Element lookup timeout in seconds."),
        limit: z.number().int().min(1).max(50).optional().describe("Maximum number of matches to return."),
        includeHtml: z.boolean().optional().describe("Include outerHTML excerpts for each match."),
        onlyVisible: z.boolean().optional().describe("Restrict results to visible elements."),
        createBrowser: z.boolean().optional().describe("Launch the browser if it is not already running."),
      },
    },
    async ({ locator, locatorType, timeout, limit, includeHtml, onlyVisible, createBrowser }) =>
      backendRequest("/api/debug/browser/query", {
        method: "POST",
        body: {
          locator,
          locator_type: locatorType ?? "raw",
          timeout: timeout ?? 1,
          limit: limit ?? 10,
          include_html: includeHtml ?? false,
          only_visible: onlyVisible ?? true,
          create_browser: createBrowser ?? false,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_action",
    {
      description:
        "Perform a simple browser debugging action on the shared tab: navigate, click, hover, scroll, clear, or input text.",
      inputSchema: {
        action: z
          .enum(["navigate", "click", "hover", "scroll", "clear", "input"])
          .describe("The browser action to perform."),
        locator: z.string().optional().describe("Element locator for non-navigate actions."),
        locatorType: z
          .enum(["raw", "css", "xpath"])
          .optional()
          .describe("How to interpret locator. raw accepts DrissionPage locators."),
        index: z.number().int().min(0).max(50).optional().describe("Which matching element to operate on."),
        timeout: z.number().min(0.1).max(5).optional().describe("Element lookup timeout in seconds."),
        onlyVisible: z.boolean().optional().describe("Only consider visible elements when resolving locator."),
        byJs: z.boolean().optional().describe("Use JS click for click actions."),
        clear: z.boolean().optional().describe("Clear existing input content before typing."),
        value: z.string().optional().describe("Input text for the input action."),
        url: z.string().url().optional().describe("Target URL for navigate."),
        navigate: z.boolean().optional().describe("If true, navigate to url before resolving the locator."),
        createBrowser: z.boolean().optional().describe("Launch the browser if it is not already running."),
      },
    },
    async ({
      action,
      locator,
      locatorType,
      index,
      timeout,
      onlyVisible,
      byJs,
      clear,
      value,
      url,
      navigate,
      createBrowser,
    }) =>
      backendRequest("/api/debug/browser/action", {
        method: "POST",
        body: {
          action,
          locator,
          locator_type: locatorType ?? "raw",
          index: index ?? 0,
          timeout: timeout ?? 1,
          only_visible: onlyVisible ?? true,
          by_js: byJs ?? true,
          clear: clear ?? true,
          value,
          url,
          navigate: navigate ?? false,
          create_browser: createBrowser ?? false,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_wait",
    {
      description:
        "Wait until the current browser reaches a specific condition, then return the final state and a fresh snapshot.",
      inputSchema: {
        condition: z
          .enum(["present", "visible", "absent", "hidden", "url_contains", "title_contains", "ready_state"])
          .describe("What condition to wait for."),
        locator: z.string().optional().describe("Element locator required for present/visible/absent/hidden conditions."),
        locatorType: z
          .enum(["raw", "css", "xpath"])
          .optional()
          .describe("How to interpret locator. raw accepts DrissionPage locators."),
        text: z.string().optional().describe("Expected text for url_contains, title_contains, or ready_state."),
        count: z.number().int().min(0).max(50).optional().describe("Required number of matched elements for present/visible conditions."),
        onlyVisible: z.boolean().optional().describe("Whether element-based waits should only consider visible matches."),
        timeout: z.number().min(0.1).max(30).optional().describe("Maximum wait time in seconds."),
        interval: z.number().min(0.02).max(1).optional().describe("Polling interval in seconds."),
        url: z.string().url().optional().describe("Optional URL to open before waiting."),
        navigate: z.boolean().optional().describe("Navigate to url before evaluating the wait condition."),
        createBrowser: z.boolean().optional().describe("Launch the browser if it is not already running."),
        includeHtml: z.boolean().optional().describe("Include a short HTML excerpt in the returned snapshot."),
        captureOnTimeout: z.boolean().optional().describe("Capture screenshot/context artifacts when the wait times out."),
      },
    },
    async ({
      condition,
      locator,
      locatorType,
      text,
      count,
      onlyVisible,
      timeout,
      interval,
      url,
      navigate,
      createBrowser,
      includeHtml,
      captureOnTimeout,
    }) =>
      backendRequest("/api/debug/browser/wait", {
        method: "POST",
        body: {
          condition,
          locator,
          locator_type: locatorType ?? "raw",
          text,
          count: count ?? 1,
          only_visible: onlyVisible ?? true,
          timeout: timeout ?? 10,
          interval: interval ?? 0.1,
          url,
          navigate: navigate ?? false,
          create_browser: createBrowser ?? false,
          include_html: includeHtml ?? false,
          capture_on_timeout: captureOnTimeout ?? true,
        },
      })
  );

  registerTool(
    server,
    "debug_browser_capture_artifacts",
    {
      description:
        "Capture a screenshot, context JSON, and optional HTML snapshot from the current browser tab for offline debugging.",
      inputSchema: {
        label: z.string().optional().describe("Optional label used in the artifact filenames."),
        includeHtml: z.boolean().optional().describe("Also persist the current page HTML."),
        sessionLabel: z.string().optional().describe("Optional session label if a debug session must be created."),
      },
    },
    async ({ label, includeHtml, sessionLabel }) =>
      backendRequest("/api/debug/browser/capture", {
        method: "POST",
        body: {
          label,
          include_html: includeHtml ?? true,
          session_label: sessionLabel,
        },
      })
  );

  registerTool(
    server,
    "get_last_browser_debug_report",
    {
      description:
        "Load the most recent automatic browser error report captured from the upload automation flow.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/debug/browser/last-error")
  );

  registerTool(
    server,
    "get_settings",
    {
      description: "Read the current automation, pricing, and model settings from the local app.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/settings")
  );

  registerTool(
    server,
    "ops_ai_policy",
    {
      description:
        "Read the local operations AI policy. External AI providers are disabled; decisions use local rules and Codex only.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/ops/ai-policy")
  );

  registerTool(
    server,
    "ops_health_check",
    {
      description:
        "Check the local operations loop readiness: Sidecar, MCP expectations, CDP/browser discovery, safety gates, and AI policy.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/ops/health")
  );

  registerTool(
    server,
    "ops_publish_preflight_safety",
    {
      description:
        "Run a local/browser safety gate before any material upload or publish-page mutation. It checks target product evidence, no-brand policy, title brand checkbox, candidate video file, and forbidden save/publish/ad/payment actions. Local-only; does not upload, save, publish, advertise, or pay.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        actionId: z.number().int().positive().optional().describe("Local ops_product_issue_actions ID to update with preflight evidence."),
        recordId: z.number().int().positive().optional().describe("Local product Record ID for title context."),
        expectedProductId: z.string().optional().describe("Expected Douyin product ID on the current edit page."),
        expectedTitle: z.string().optional().describe("Expected product title on the current page."),
        candidateVideoPath: z.string().optional().describe("Optional absolute path to candidate-main-video.mp4."),
      },
    },
    async ({ actionId, recordId, expectedProductId, expectedTitle, candidateVideoPath }) =>
      backendRequest("/api/ops/publish-preflight-safety", {
        method: "POST",
        body: {
          action_id: actionId,
          record_id: recordId,
          expected_product_id: expectedProductId,
          expected_title: expectedTitle,
          candidate_video_path: candidateVideoPath,
        },
      })
  );

  registerTool(
    server,
    "ops_upload_main_video_preflight",
    {
      description:
        "Upload only the candidate main product video through the logged-in browser, then stop before save, draft save, publish, ad spend, or payment. Requires the no-brand publish preflight to pass first; local-only and does not call official APIs or external AI.",
      annotations: { readOnlyHint: false },
      inputSchema: {
        actionId: z.number().int().positive().optional().describe("Local ops_product_issue_actions ID to update with upload evidence."),
        recordId: z.number().int().positive().optional().describe("Local product Record ID for title context."),
        expectedProductId: z.string().optional().describe("Expected Douyin product ID on the current edit page."),
        expectedTitle: z.string().optional().describe("Expected product title on the current page."),
        candidateVideoPath: z.string().optional().describe("Optional absolute path to candidate-main-video.mp4."),
      },
    },
    async ({ actionId, recordId, expectedProductId, expectedTitle, candidateVideoPath }) =>
      backendRequest("/api/ops/upload-main-video-preflight", {
        method: "POST",
        body: {
          action_id: actionId,
          record_id: recordId,
          expected_product_id: expectedProductId,
          expected_title: expectedTitle,
          candidate_video_path: candidateVideoPath,
        },
      })
  );

  registerTool(
    server,
    "ops_save_edit_human_gate",
    {
      description:
        "Check whether the current product edit page is ready for a human-confirmed save after a safe main-video upload. This never clicks save, draft save, publish, ads, or payment; it only returns blockers and records local evidence.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        actionId: z.number().int().positive().optional().describe("Local ops_product_issue_actions ID to update with save-gate evidence."),
        recordId: z.number().int().positive().optional().describe("Local product Record ID for title context."),
        expectedProductId: z.string().optional().describe("Expected Douyin product ID on the current edit page."),
        expectedTitle: z.string().optional().describe("Expected product title on the current page."),
        candidateVideoPath: z.string().optional().describe("Optional absolute path to candidate-main-video.mp4."),
      },
    },
    async ({ actionId, recordId, expectedProductId, expectedTitle, candidateVideoPath }) =>
      backendRequest("/api/ops/save-edit-human-gate", {
        method: "POST",
        body: {
          action_id: actionId,
          record_id: recordId,
          expected_product_id: expectedProductId,
          expected_title: expectedTitle,
          candidate_video_path: candidateVideoPath,
        },
      })
  );

  registerTool(
    server,
    "ops_read_shop_metrics_cdp",
    {
      description:
        "Read visible Douyin Shop operations metrics from the current FXG browser page via CDP. This is read-only and does not call official APIs or external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional().describe("Defaults to fxg.jinritemai.com."),
        useTemporaryTab: z.boolean().optional().describe("Open a temporary FXG tab for metrics, read it, then close it. Keeps the current edit page untouched."),
        navigateUrl: z.string().url().optional().describe("FXG page to open in the temporary tab. Defaults to the shop homepage."),
        waitMs: z.number().int().min(500).max(15000).optional().describe("Wait after opening the temporary tab before reading visible text."),
        textLimit: z.number().int().min(1000).max(100000).optional(),
      },
    },
    async ({ cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit }) =>
      readShopMetricsViaCdp({ cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit })
  );

  registerTool(
    server,
    "ops_read_strategy_signals_cdp",
    {
      description:
        "Read visible Douyin Shop strategy signals via CDP, such as product diagnostics, missing videos/spec images, opportunity keywords, risk-product counts, and refund reasons. Read-only; no official API or external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional().describe("Defaults to fxg.jinritemai.com."),
        useTemporaryTab: z.boolean().optional().describe("Open a temporary FXG tab for strategy signals, read it, then close it. Keeps the current edit page untouched."),
        navigateUrl: z.string().url().optional().describe("Optional FXG page URL to navigate before reading, for example the product diagnosis page."),
        waitMs: z.number().int().min(500).max(15000).optional().describe("Wait after navigation before reading visible text."),
        textLimit: z.number().int().min(1000).max(100000).optional(),
      },
    },
    async ({ cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit }) =>
      readStrategySignalsViaCdp({ cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit })
  );

  registerTool(
    server,
    "ops_sync_strategy_signals",
    {
      description:
        "Persist Douyin Shop strategy and product diagnosis signals into the local ops ledger. If signals are omitted, reads them first via CDP from a logged-in FXG page. Read-only toward FXG; writes only to the local SQLite ledger.",
      inputSchema: {
        signals: z
          .record(z.string(), z.any())
          .optional()
          .describe("Observed strategy signals from ops_read_strategy_signals_cdp."),
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional().describe("Defaults to fxg.jinritemai.com."),
        useTemporaryTab: z.boolean().optional().describe("Open a temporary FXG tab for strategy signals, read it, then close it. Keeps the current edit page untouched."),
        navigateUrl: z.string().url().optional().describe("Optional FXG page URL to navigate before reading, for example the product diagnosis page."),
        waitMs: z.number().int().min(500).max(15000).optional().describe("Wait after navigation before reading visible text."),
        textLimit: z.number().int().min(1000).max(100000).optional(),
      },
    },
    async ({ signals, cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit }) => {
      const hasInputSignals = signals && Object.keys(signals).length > 0;
      if (hasInputSignals) {
        return backendRequest("/api/ops/sync-strategy-signals", {
          method: "POST",
          body: {
            signals,
            source: signals.source || "manual",
          },
        });
      }

      const cdpRead = await readStrategySignalsViaCdp({
        cdpListUrl,
        targetUrlContains,
        useTemporaryTab,
        navigateUrl,
        waitMs,
        textLimit,
      });
      const synced = await backendRequest("/api/ops/sync-strategy-signals", {
        method: "POST",
        body: {
          signals: cdpRead.signals ?? {},
          source: "cdp_browser",
          browser: cdpRead.browser ?? {},
          audit_metrics: cdpRead.auditMetrics ?? [],
          raw_payload: cdpRead.raw_payload ?? {},
        },
      });
      return {
        ...synced,
        data: {
          ...(synced?.data ?? {}),
          cdp_read: {
            success: cdpRead.success,
            reason: cdpRead.reason,
            target: cdpRead.target,
            browser: cdpRead.browser,
            signals: cdpRead.signals,
          },
        },
      };
    }
  );

  registerTool(
    server,
    "ops_product_issue_actions",
    {
      description:
        "List persisted local product diagnosis action items and status-change events. Read-only; use this before deciding which material or detail-page issue to work on.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(100).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        actionId: z.number().int().positive().optional().describe("If supplied, include events for this action ID."),
      },
    },
    async ({ limit, actionStatus, actionId }) =>
      backendRequest("/api/ops/product-issue-actions", {
        query: {
          limit,
          action_status: actionStatus,
          action_id: actionId,
        },
      })
  );

  registerTool(
    server,
    "ops_no_brand_title_audit",
    {
      description:
        "Audit local product diagnosis action titles for brand residue under the no-brand policy. Read-only; does not edit online products, save, publish, advertise, or pay.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
      },
    },
    async ({ limit, actionStatus }) =>
      backendRequest("/api/ops/no-brand-title-audit", {
        query: {
          limit,
          action_status: actionStatus,
        },
      })
  );

  registerTool(
    server,
    "ops_no_brand_remediation_plan",
    {
      description:
        "Build a local-only remediation plan for product titles with brand residue under the no-brand policy. It proposes sanitized titles and read-only browser gates, but never saves, publishes, advertises, pays, purchases, or calls external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
      },
    },
    async ({ limit, actionStatus, productIssueActions }) =>
      backendRequest("/api/ops/no-brand-remediation-plan", {
        method: "POST",
        body: {
          limit,
          action_status: actionStatus,
          product_issue_actions: productIssueActions,
        },
      })
  );

  registerTool(
    server,
    "ops_reconcile_strategy_actions",
    {
      description:
        "Reconcile duplicate product diagnosis actions after a fresh strategy snapshot. It can inherit prior blocked/in-progress states and block brand-residue titles in the local ledger only; it never clicks FXG, saves, publishes, advertises, pays, purchases, or calls external AI.",
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        latestStrategySnapshotId: z.number().int().positive().optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
        apply: z.boolean().optional().describe("Default false. If true, apply only local SQLite action-status updates."),
      },
    },
    async ({ limit, latestStrategySnapshotId, productIssueActions, apply }) => {
      const request = buildStrategyActionReconcileRequest({
        productIssueActions,
        latestStrategySnapshotId,
        limit,
        apply: apply ?? false,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_update_product_issue_action",
    {
      description:
        "Update the local status of a product diagnosis action item with a note and evidence. This does not click FXG optimization buttons or mutate the shop; it only records local operations progress.",
      inputSchema: {
        actionId: z.number().int().positive().describe("Local ops_product_issue_actions ID."),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]),
        note: z.string().optional().describe("Short evidence-backed progress note."),
        evidence: z.record(z.string(), z.any()).optional().describe("Structured evidence such as page URL, local record ID, or material path."),
      },
    },
    async ({ actionId, actionStatus, note, evidence }) =>
      backendRequest(`/api/ops/product-issue-actions/${actionId}`, {
        method: "POST",
        body: {
          action_status: actionStatus,
          note,
          evidence,
        },
      })
  );

  registerTool(
    server,
    "ops_sync_product_record_mappings",
    {
      description:
        "Match persisted Douyin Shop product diagnosis actions to local product Records by conservative title similarity and persist the mapping result. Local-only; does not call FXG APIs or mutate the shop.",
      inputSchema: {
        limit: z.number().int().positive().max(200).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        minConfidence: z.number().min(0).max(1).optional().describe("Default 0.72. Lower values are less conservative."),
      },
    },
    async ({ limit, actionStatus, minConfidence }) =>
      backendRequest("/api/ops/sync-product-record-mappings", {
        method: "POST",
        body: {
          limit,
          action_status: actionStatus,
          minConfidence,
        },
      })
  );

  registerTool(
    server,
    "ops_product_record_mappings",
    {
      description:
        "Read the latest persisted mapping results between Douyin Shop product IDs and local Records.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(200).optional(),
        matchStatus: z.enum(["matched", "unmatched"]).optional(),
      },
    },
    async ({ limit, matchStatus }) =>
      backendRequest("/api/ops/product-record-mappings", {
        query: {
          limit,
          match_status: matchStatus,
        },
      })
  );

  registerTool(
    server,
    "ops_material_gap_plan",
    {
      description:
        "Build a local-only material collection plan from product diagnosis actions and Record mappings. Separates revenue-blocked material gaps, no-brand title risks, and open missing-material items. Read-only; does not save, publish, advertise, pay, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
        productRecordMappings: z.array(z.record(z.string(), z.any())).optional(),
        noBrandAudit: z.record(z.string(), z.any()).optional(),
      },
    },
    async ({ limit, actionStatus, productIssueActions, productRecordMappings, noBrandAudit }) =>
      backendRequest("/api/ops/material-gap-plan", {
        method: "POST",
        body: {
          limit,
          action_status: actionStatus,
          product_issue_actions: productIssueActions,
          product_record_mappings: productRecordMappings,
          no_brand_audit: noBrandAudit,
        },
      })
  );

  registerTool(
    server,
    "ops_sourcing_profit_gate",
    {
      description:
        "Build a local-only procurement profit gate before sourcing or stocking a product. It calculates supplier cost ceilings, unit profit, daily orders needed for 500 CNY net profit, and safety boundaries. Read-only; does not purchase, pay, save, publish, advertise, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        product: z.record(z.string(), z.any()).optional(),
        actionId: z.number().int().positive().optional(),
        targetNetProfit: z.number().positive().optional(),
        scenarios: z.array(z.record(z.string(), z.any())).optional(),
      },
    },
    async ({ product, actionId, targetNetProfit, scenarios }) =>
      backendRequest("/api/ops/sourcing-profit-gate", {
        method: "POST",
        body: {
          product,
          action_id: actionId,
          target_net_profit: targetNetProfit,
          scenarios: scenarios ?? [],
        },
      })
  );

  registerTool(
    server,
    "ops_supplier_quote_plan",
    {
      description:
        "Build a local-only supplier inquiry and quote evaluation plan for a target Douyin product. Scores exact-style evidence, no-brand confirmation, supplier cost, MOQ, shipping, material proof, and stock colors. Read-only; does not purchase, pay, save, publish, advertise, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        product: z.record(z.string(), z.any()).optional(),
        actionId: z.number().int().positive().optional(),
        sourcingProfitGate: z.record(z.string(), z.any()).optional(),
        scenarios: z.array(z.record(z.string(), z.any())).optional(),
        supplierCandidates: z.array(z.record(z.string(), z.any())).optional(),
      },
    },
    async ({ product, actionId, sourcingProfitGate, scenarios, supplierCandidates }) =>
      backendRequest("/api/ops/supplier-quote-plan", {
        method: "POST",
        body: {
          product,
          action_id: actionId,
          sourcing_profit_gate: sourcingProfitGate,
          scenarios: scenarios ?? [],
          supplier_candidates: supplierCandidates ?? [],
        },
      })
  );

  registerTool(
    server,
    "ops_supplier_quote_intake",
    {
      description:
        "Evaluate a returned supplier quote against the sourcing profit gate, exact-style evidence, no-brand confirmation, MOQ, shipping, and material proof. Local-only; does not purchase, pay, save, publish, advertise, stock in bulk, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        product: z.record(z.string(), z.any()).optional(),
        actionId: z.number().int().positive().optional(),
        sourcingProfitGate: z.record(z.string(), z.any()).optional(),
        scenarios: z.array(z.record(z.string(), z.any())).optional(),
        supplierQuote: z.record(z.string(), z.any()).describe("Returned quote and evidence from a supplier."),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({ product, actionId, sourcingProfitGate, scenarios, supplierQuote, targetNetProfit }) =>
      backendRequest("/api/ops/supplier-quote-intake", {
        method: "POST",
        body: {
          product,
          action_id: actionId,
          sourcing_profit_gate: sourcingProfitGate,
          scenarios: scenarios ?? [],
          supplier_quote: supplierQuote,
          target_net_profit: targetNetProfit,
        },
      })
  );

  registerTool(
    server,
    "ops_execution_queue",
    {
      description:
        "Build a local-only prioritized daily operations queue from the latest metrics, issue actions, material gaps, and supplier quote plan. It keeps no-brand policy, pauses paid ads, and never saves, publishes, advertises, pays, purchases, or calls external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        metrics: z.record(z.string(), z.any()).optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
        productRecordMappings: z.array(z.record(z.string(), z.any())).optional(),
        materialGapPlan: z.record(z.string(), z.any()).optional(),
        supplierQuotePlan: z.record(z.string(), z.any()).optional(),
        supplierQuotePlans: z.array(z.record(z.string(), z.any())).optional(),
        conversionExperimentPlan: z.record(z.string(), z.any()).optional(),
        noBrandAudit: z.record(z.string(), z.any()).optional(),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({
      limit,
      actionStatus,
      metrics,
      productIssueActions,
      productRecordMappings,
      materialGapPlan,
      supplierQuotePlan,
      supplierQuotePlans,
      conversionExperimentPlan,
      noBrandAudit,
      targetNetProfit,
    }) =>
      backendRequest("/api/ops/execution-queue", {
        method: "POST",
        body: {
          limit,
          action_status: actionStatus,
          metrics,
          product_issue_actions: productIssueActions,
          product_record_mappings: productRecordMappings,
          material_gap_plan: materialGapPlan,
          supplier_quote_plan: supplierQuotePlan,
          supplier_quote_plans: supplierQuotePlans,
          conversion_experiment_plan: conversionExperimentPlan,
          no_brand_audit: noBrandAudit,
          target_net_profit: targetNetProfit,
        },
      })
  );

  registerTool(
    server,
    "ops_portfolio_path_to_500",
    {
      description:
        "Build a local-only multi-product portfolio path toward 500 CNY/day net profit from current metrics and issue actions. It ranks action lanes, preserves no-brand policy, and keeps paid ads, purchase, save, publish, and payment blocked until real evidence is verified.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
        actionStatus: z.enum(["open", "in_progress", "done", "blocked", "skipped"]).optional(),
        metrics: z.record(z.string(), z.any()).optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({ limit, actionStatus, metrics, productIssueActions, targetNetProfit }) => {
      const request = buildPortfolioPathTo500Request({
        limit,
        actionStatus,
        metrics,
        productIssueActions,
        targetNetProfit,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_first_order_decision_matrix",
    {
      description:
        "Build a local-only first-order decision matrix for the human-confirmed save path. It compares baseline/current metrics and branches into wait, conversion bottleneck, card-click bottleneck, or profit validation. Read-only; does not save, publish, advertise, pay, purchase, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        baselineMetrics: z.record(z.string(), z.any()).optional(),
        currentMetrics: z.record(z.string(), z.any()).optional(),
        metrics: z.record(z.string(), z.any()).optional(),
        action: z.record(z.string(), z.any()).optional(),
        actionId: z.number().int().positive().optional(),
        saveGate: z.record(z.string(), z.any()).optional(),
        targetNetProfit: z.number().positive().optional(),
        savedConfirmed: z.boolean().optional(),
      },
    },
    async ({
      baselineMetrics,
      currentMetrics,
      metrics,
      action,
      actionId,
      saveGate,
      targetNetProfit,
      savedConfirmed,
    }) => {
      const request = buildFirstOrderDecisionMatrixRequest({
        baselineMetrics,
        currentMetrics,
        metrics,
        action,
        actionId,
        saveGate,
        targetNetProfit,
        savedConfirmed,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_net_profit_verification_matrix",
    {
      description:
        "Build a local-only net profit verification matrix from order rows and complete cost evidence. It refuses to mark net profit verified when orders or required cost fields are missing. Read-only; does not save, publish, advertise, pay, purchase, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        orders: z.array(z.record(z.string(), z.any())).optional(),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({ orders, targetNetProfit }) => {
      const request = buildNetProfitVerificationMatrixRequest({
        orders,
        targetNetProfit,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_post_save_conversion_monitor",
    {
      description:
        "Build a local-only post-save conversion monitor for the human-confirmed edit save path. Read-only; does not save, publish, advertise, pay, purchase, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        action: z.record(z.string(), z.any()).optional(),
        actionId: z.number().int().positive().optional(),
        saveGate: z.record(z.string(), z.any()).optional(),
        conversionExperimentPlan: z.record(z.string(), z.any()).optional(),
        targetNetProfit: z.number().positive().optional(),
        savedConfirmed: z.boolean().optional(),
      },
    },
    async ({
      metrics,
      action,
      actionId,
      saveGate,
      conversionExperimentPlan,
      targetNetProfit,
      savedConfirmed,
    }) => {
      const request = buildPostSaveConversionMonitorRequest({
        metrics,
        action,
        actionId,
        saveGate,
        conversionExperimentPlan,
        targetNetProfit,
        savedConfirmed,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_sync_shop_metrics",
    {
      description:
        "Persist a daily operations metric snapshot. If metrics are omitted, first tries to read visible FXG shop metrics via CDP. Does not fabricate net profit.",
      inputSchema: {
        metrics: z
          .record(z.string(), z.any())
          .optional()
          .describe("Observed shop metrics such as net_profit, gross_sales, promotion_cost, status, and notes."),
        source: z.string().optional().describe("Metric source label, for example browser, cdp, or manual."),
        cdpListUrl: z.string().url().optional(),
        targetUrlContains: z.string().optional().describe("Defaults to fxg.jinritemai.com."),
        useTemporaryTab: z.boolean().optional().describe("Open a temporary FXG tab for metrics, read it, then close it. Keeps the current edit page untouched."),
        navigateUrl: z.string().url().optional().describe("FXG page to open in the temporary tab. Defaults to the shop homepage."),
        waitMs: z.number().int().min(500).max(15000).optional().describe("Wait after opening the temporary tab before reading visible text."),
        textLimit: z.number().int().min(1000).max(100000).optional(),
      },
    },
    async ({ metrics, source, cdpListUrl, targetUrlContains, useTemporaryTab, navigateUrl, waitMs, textLimit }) => {
      const hasInputMetrics = metrics && Object.keys(metrics).length > 0;
      if (hasInputMetrics) {
        return backendRequest("/api/ops/sync-shop-metrics", {
          method: "POST",
          body: {
            metrics,
            source,
          },
        });
      }

      const cdpRead = await readShopMetricsViaCdp({
        cdpListUrl,
        targetUrlContains,
        useTemporaryTab,
        navigateUrl,
        waitMs,
        textLimit,
      });
      const synced = await backendRequest("/api/ops/sync-shop-metrics", {
        method: "POST",
        body: {
          metrics: cdpRead.metrics ?? {},
          source: source || "cdp_browser",
          browser: cdpRead.browser ?? {},
          audit_metrics: cdpRead.auditMetrics ?? [],
          raw_payload: cdpRead.raw_payload ?? {},
        },
      });
      return {
        ...synced,
        data: {
          ...(synced?.data ?? {}),
          cdp_read: {
            success: cdpRead.success,
            reason: cdpRead.reason,
            target: cdpRead.target,
            browser: cdpRead.browser,
            metrics: cdpRead.metrics,
          },
        },
      };
    }
  );

  registerTool(
    server,
    "ops_evaluate_product",
    {
      description:
        "Calculate operating net profit for one product and persist a product evaluation snapshot.",
      inputSchema: {
        recordId: z.number().int().positive().optional().describe("Product record ID."),
        title: z.string().optional().describe("Product title if no record ID is supplied."),
        salePrice: z.number().nonnegative().optional().describe("Final sale price per order."),
        goodsCost: z.number().nonnegative().describe("Offline goods cost per order."),
        shippingCost: z.number().nonnegative().optional().describe("Shipping cost per order."),
        packagingCost: z.number().nonnegative().optional().describe("Packaging cost per order."),
        platformCommissionRate: z
          .number()
          .nonnegative()
          .optional()
          .describe("Platform commission rate, either 0.05 or 5 for 5%."),
        promotionCost: z.number().nonnegative().optional().describe("Promotion cost allocated per order."),
        refundLoss: z.number().nonnegative().optional().describe("Expected refund loss per order."),
        afterSaleLoss: z.number().nonnegative().optional().describe("Expected after-sale loss per order."),
        expectedDailyOrders: z.number().int().nonnegative().optional().describe("Expected daily order count."),
      },
    },
    async ({
      recordId,
      title,
      salePrice,
      goodsCost,
      shippingCost,
      packagingCost,
      platformCommissionRate,
      promotionCost,
      refundLoss,
      afterSaleLoss,
      expectedDailyOrders,
    }) =>
      backendRequest("/api/ops/evaluate-product", {
        method: "POST",
        body: {
          record_id: recordId,
          title,
          sale_price: salePrice,
          goods_cost: goodsCost,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
          refund_loss: refundLoss,
          after_sale_loss: afterSaleLoss,
          expected_daily_orders: expectedDailyOrders,
        },
      })
  );

  registerTool(
    server,
    "ops_stock_plan",
    {
      description:
        "Generate a conservative pre-launch stock plan for a sock product to reduce inventory pile-up risk.",
      inputSchema: {
        recordId: z.number().int().positive().optional().describe("Product record ID."),
        skuCount: z.number().int().positive().optional().describe("SKU count if no record ID is supplied."),
        expectedDailyOrders: z.number().int().nonnegative().optional().describe("Expected daily order count."),
        replenishmentDays: z.number().int().positive().optional().describe("Days needed to replenish offline stock."),
        canRestockSameDay: z.boolean().optional().describe("Whether the local market can replenish the same day."),
        maxPerSkuWithoutSalesSignal: z
          .number()
          .int()
          .positive()
          .optional()
          .describe("Trial stock per SKU when there is no sales signal."),
      },
    },
    async ({
      recordId,
      skuCount,
      expectedDailyOrders,
      replenishmentDays,
      canRestockSameDay,
      maxPerSkuWithoutSalesSignal,
    }) =>
      backendRequest("/api/ops/stock-plan", {
        method: "POST",
        body: {
          record_id: recordId,
          sku_count: skuCount,
          expected_daily_orders: expectedDailyOrders,
          replenishment_days: replenishmentDays,
          can_restock_same_day: canRestockSameDay,
          max_per_sku_without_sales_signal: maxPerSkuWithoutSalesSignal,
        },
      })
  );

  registerTool(
    server,
    "ops_product_candidates",
    {
      description:
        "Evaluate local product records as operations candidates using SKU prices as goods cost, recommended sale price, per-order net profit, target orders for 500 CNY/day, and conservative trial stock.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        limit: z.number().int().positive().max(100).optional(),
        targetNetMargin: z.number().nonnegative().optional().describe("Target net margin, e.g. 0.30 or 30."),
        expectedDailyOrders: z.number().int().nonnegative().optional(),
        shippingCost: z.number().nonnegative().optional(),
        packagingCost: z.number().nonnegative().optional(),
        platformCommissionRate: z.number().nonnegative().optional().describe("Commission rate, e.g. 0.05 or 5."),
        promotionCost: z.number().nonnegative().optional().describe("Promotion cost allocated per order."),
      },
    },
    async ({
      limit,
      targetNetMargin,
      expectedDailyOrders,
      shippingCost,
      packagingCost,
      platformCommissionRate,
      promotionCost,
    }) =>
      backendRequest("/api/ops/product-candidates", {
        method: "POST",
        body: {
          limit,
          target_net_margin: targetNetMargin,
          expected_daily_orders: expectedDailyOrders,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
        },
      })
  );

  registerTool(
    server,
    "ops_apply_candidate_pricing",
    {
      description:
        "Apply or dry-run the recommended operations sale price to all SKUs in a local product record. Preserves the old SKU price as ops_goods_cost so future profit analysis still uses goods cost.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        salePrice: z.number().positive().optional().describe("Sale price to apply. Defaults to candidate recommended_sale_price."),
        dryRun: z.boolean().optional().describe("Default true. Set false to persist the local product price change."),
        targetNetMargin: z.number().nonnegative().optional(),
        shippingCost: z.number().nonnegative().optional(),
        packagingCost: z.number().nonnegative().optional(),
        platformCommissionRate: z.number().nonnegative().optional(),
        promotionCost: z.number().nonnegative().optional(),
      },
    },
    async ({ recordId, salePrice, dryRun, targetNetMargin, shippingCost, packagingCost, platformCommissionRate, promotionCost }) =>
      backendRequest("/api/ops/apply-candidate-pricing", {
        method: "POST",
        body: {
          record_id: recordId,
          sale_price: salePrice,
          dry_run: dryRun ?? true,
          target_net_margin: targetNetMargin,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
        },
      })
  );

  registerTool(
    server,
    "ops_daily_plan",
    {
      description:
        "Build the daily operations action plan from the latest snapshot or provided metrics.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z
          .record(z.string(), z.any())
          .optional()
          .describe("Optional daily metrics including net_profit, ready_products, blocked_products, and low_stock_products."),
        diagnosticSignals: z
          .record(z.string(), z.any())
          .optional()
          .describe("Optional product diagnosis and strategy signals from ops_read_strategy_signals_cdp."),
      },
    },
    async ({ metrics, diagnosticSignals }) =>
      backendRequest("/api/ops/daily-plan", {
        method: "POST",
        body: {
          metrics: metrics ?? {},
          diagnostic_signals: diagnosticSignals,
        },
      })
  );

  registerTool(
    server,
    "ops_search_conversion_work_package",
    {
      description:
        "Build a local-only search conversion work package from visible FXG metrics and issue actions. It proposes no-brand search terms and manual 看后搜/小蓝词 gates, but never configures the platform, saves, publishes, advertises, pays, purchases, or calls external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        productIssueActions: z.array(z.record(z.string(), z.any())).optional(),
        actionId: z.number().int().positive().optional(),
        targetNetProfit: z.number().positive().optional(),
        limit: z.number().int().min(1).max(500).optional(),
      },
    },
    async ({ metrics, productIssueActions, actionId, targetNetProfit, limit }) => {
      const request = buildSearchConversionWorkPackageRequest({
        metrics,
        productIssueActions,
        actionId,
        targetNetProfit,
        limit,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_daily_review",
    {
      description:
        "Build a daily operations review combining the latest real shop metrics snapshot with local product candidates. Shows goal status, top candidate, price/stock actions, and safety boundaries.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        diagnosticSignals: z.record(z.string(), z.any()).optional(),
        limit: z.number().int().positive().max(100).optional(),
        targetNetMargin: z.number().nonnegative().optional(),
        expectedDailyOrders: z.number().int().nonnegative().optional(),
        shippingCost: z.number().nonnegative().optional(),
        packagingCost: z.number().nonnegative().optional(),
        platformCommissionRate: z.number().nonnegative().optional(),
        promotionCost: z.number().nonnegative().optional(),
      },
    },
    async ({
      metrics,
      diagnosticSignals,
      limit,
      targetNetMargin,
      expectedDailyOrders,
      shippingCost,
      packagingCost,
      platformCommissionRate,
      promotionCost,
    }) =>
      backendRequest("/api/ops/daily-review", {
        method: "POST",
        body: {
          metrics: metrics ?? {},
          diagnostic_signals: diagnosticSignals,
          limit,
          target_net_margin: targetNetMargin,
          expected_daily_orders: expectedDailyOrders,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
        },
      })
  );

  registerTool(
    server,
    "ops_detail_conversion_audit",
    {
      description:
        "Turn a browser-read current edit-page snapshot into a safe detail-conversion audit for clicked-but-no-order products. Read-only; does not save, publish, advertise, or pay.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        productTitle: z.string().optional(),
        pageSnapshot: z.record(z.string(), z.any()).describe("Current edit-page evidence read via browser/CDP."),
      },
    },
    async ({ metrics, productTitle, pageSnapshot }) =>
      backendRequest("/api/ops/detail-conversion-audit", {
        method: "POST",
        body: {
          metrics,
          product_title: productTitle,
          page_snapshot: pageSnapshot,
        },
      })
  );

  registerTool(
    server,
    "ops_profit_ramp_plan",
    {
      description:
        "Quantify the path to 500 CNY/day net profit from latest real metrics and local product candidates: required orders, validation traffic, stage, paid-ad readiness, and safety gates. Local-only; no official API or external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        limit: z.number().int().positive().max(100).optional(),
        targetNetMargin: z.number().nonnegative().optional(),
        expectedDailyOrders: z.number().int().nonnegative().optional(),
        shippingCost: z.number().nonnegative().optional(),
        packagingCost: z.number().nonnegative().optional(),
        platformCommissionRate: z.number().nonnegative().optional(),
        promotionCost: z.number().nonnegative().optional(),
      },
    },
    async ({
      metrics,
      limit,
      targetNetMargin,
      expectedDailyOrders,
      shippingCost,
      packagingCost,
      platformCommissionRate,
      promotionCost,
    }) =>
      backendRequest("/api/ops/profit-ramp-plan", {
        method: "POST",
        body: {
          metrics: metrics ?? {},
          limit,
          target_net_margin: targetNetMargin,
          expected_daily_orders: expectedDailyOrders,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
        },
      })
  );

  registerTool(
    server,
    "ops_profit_ladder_to_500",
    {
      description:
        "Build a local-only cost ladder for one product showing net profit per order and required daily orders to reach 500 CNY net profit. Keeps no-brand policy and pauses paid scale until first-order and cost evidence are verified.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        product: z.record(z.string(), z.any()).describe("Product economics: sale_price, shipping_cost, packaging_cost, platform_commission_rate, refund_loss, action_id, product_id, title."),
        costScenarios: z.array(z.record(z.string(), z.any())).optional(),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({ metrics, product, costScenarios, targetNetProfit }) => {
      const request = buildProfitLadderTo500Request({
        metrics,
        product,
        costScenarios,
        targetNetProfit,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_conversion_asset_pack",
    {
      description:
        "Build a local-only no-brand conversion asset pack for detail first-screen and spec image drafts. Read-only; does not upload, save, publish, advertise, pay, purchase, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        product: z.record(z.string(), z.any()).describe("Product context: action_id, product_id, title, sale_price."),
        detailAudit: z.record(z.string(), z.any()).optional(),
        pageSnapshot: z.record(z.string(), z.any()).optional(),
        suggestions: z.record(z.string(), z.any()).optional(),
        targetNetProfit: z.number().positive().optional(),
      },
    },
    async ({ metrics, product, detailAudit, pageSnapshot, suggestions, targetNetProfit }) => {
      const request = buildConversionAssetPackRequest({
        metrics,
        product,
        detailAudit,
        pageSnapshot,
        suggestions,
        targetNetProfit,
      });
      return backendRequest(request.path, {
        method: request.method,
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "ops_conversion_experiment_plan",
    {
      description:
        "Build a local-only conversion experiment plan from latest metrics, detail audit, and profit ramp plan. Read-only; does not save, publish, advertise, pay, or call external AI.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        metrics: z.record(z.string(), z.any()).optional(),
        detailAudit: z.record(z.string(), z.any()).optional(),
        pageSnapshot: z.record(z.string(), z.any()).optional(),
        profitPlan: z.record(z.string(), z.any()).optional(),
        limit: z.number().int().positive().max(100).optional(),
        targetNetMargin: z.number().nonnegative().optional(),
        expectedDailyOrders: z.number().int().nonnegative().optional(),
        shippingCost: z.number().nonnegative().optional(),
        packagingCost: z.number().nonnegative().optional(),
        platformCommissionRate: z.number().nonnegative().optional(),
        promotionCost: z.number().nonnegative().optional(),
      },
    },
    async ({
      metrics,
      detailAudit,
      pageSnapshot,
      profitPlan,
      limit,
      targetNetMargin,
      expectedDailyOrders,
      shippingCost,
      packagingCost,
      platformCommissionRate,
      promotionCost,
    }) =>
      backendRequest("/api/ops/conversion-experiment-plan", {
        method: "POST",
        body: {
          metrics: metrics ?? {},
          detail_audit: detailAudit,
          page_snapshot: pageSnapshot,
          profit_plan: profitPlan,
          limit,
          target_net_margin: targetNetMargin,
          expected_daily_orders: expectedDailyOrders,
          shipping_cost: shippingCost,
          packaging_cost: packagingCost,
          platform_commission_rate: platformCommissionRate,
          promotion_cost: promotionCost,
        },
      })
  );

  registerTool(
    server,
    "update_settings",
    {
      description:
        "Persist settings changes to the local app. Pass only the top-level settings keys you want to update.",
      inputSchema: {
        settings: z
          .object({
            automation_config: z
              .object({
                shipping_template: z.string().optional(),
                shipping_templates: z.array(z.string()).optional(),
                material_compositions: z
                  .array(
                    z.object({
                      material: z.string().min(1),
                      percentage: z.number().positive(),
                    })
                  )
                  .optional(),
              })
              .optional(),
          })
          .passthrough()
          .describe("Partial settings object to merge into the local settings file."),
      },
    },
    async ({ settings }) => updateSettings(settings)
  );

  registerTool(
    server,
    "reset_settings",
    {
      description: "Reset the local app settings back to defaults.",
    },
    async () => resetSettings()
  );

  registerTool(
    server,
    "list_category_options",
    {
      description: "List the supported local product category codes and labels.",
      annotations: { readOnlyHint: true },
    },
    async () => ({ categories: getCategoryOptions() })
  );

  registerTool(
    server,
    "list_products",
    {
      description: "List products currently loaded in the local Douyin publisher database.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/products")
  );

  registerTool(
    server,
    "get_product_detail",
    {
      description: "Load a product with SKU details. Keep loadImages=false unless images are explicitly needed.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        loadImages: z
          .boolean()
          .optional()
          .describe("Whether to include base64-encoded SKU images."),
      },
    },
    async ({ recordId, loadImages }) => fetchProductDetail(recordId, loadImages ?? false)
  );

  registerTool(
    server,
    "list_sku_assets",
    {
      description:
        "List every SKU with its display name, price, image path, and optionally the base64-encoded image payload.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        includeBase64: z
          .boolean()
          .optional()
          .describe("Whether to include the base64-encoded SKU image content."),
      },
    },
    async ({ recordId, includeBase64 }) =>
      listSkuAssets(recordId, {
        includeBase64: includeBase64 ?? false,
      })
  );

  registerTool(
    server,
    "list_product_files",
    {
      description:
        "List the local files under one product folder. Use mediaOnly=true to restrict the result to images and videos.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        maxDepth: z.number().int().min(0).max(8).optional().describe("Maximum recursion depth."),
        mediaOnly: z.boolean().optional().describe("Only include image and video files."),
        includeDirectories: z
          .boolean()
          .optional()
          .describe("Whether to include directories in the returned file list."),
      },
    },
    async ({ recordId, maxDepth, mediaOnly, includeDirectories }) =>
      listProductFiles(recordId, {
        maxDepth: maxDepth ?? 4,
        mediaOnly: mediaOnly ?? false,
        includeDirectories: includeDirectories ?? true,
      })
  );

  registerTool(
    server,
    "get_product_asset_manifest",
    {
      description:
        "Inspect the local media assets for one product, grouped into SKU images, main images, 3:4 images, detail images, white-background images, and videos.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        maxDepth: z.number().int().min(0).max(8).optional().describe("Maximum recursion depth."),
      },
    },
    async ({ recordId, maxDepth }) =>
      buildProductAssetManifest(recordId, {
        maxDepth: maxDepth ?? 4,
      })
  );

  registerTool(
    server,
    "validate_product_assets",
    {
      description:
        "Check whether the local product folder contains the expected upload assets, including SKU images, main images, 3:4 images, and detail images.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        maxDepth: z.number().int().min(0).max(8).optional().describe("Maximum recursion depth."),
      },
    },
    async ({ recordId, maxDepth }) =>
      validateProductAssets(recordId, {
        maxDepth: maxDepth ?? 4,
      })
  );

  registerTool(
    server,
    "validate_product_for_upload",
    {
      description:
        "Run upload-readiness checks on a single product, including title, category, SKU names, prices, duplicate SKU names, and required local media assets.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
      },
    },
    async ({ recordId }) => buildUploadReadiness(recordId)
  );

  registerTool(
    server,
    "prepare_product_draft",
    {
      description:
        "Generate a preparation draft for one product: title suggestions, smart prices, and readiness before and after applying the draft.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z.number().positive().describe("Base cost per pair of socks."),
        enhanced: z.boolean().optional().describe("Use enhanced title generation."),
        useTrending: z
          .boolean()
          .optional()
          .describe("Whether enhanced title generation should load trending keywords."),
        titleIndex: z
          .number()
          .int()
          .min(0)
          .optional()
          .describe("Which generated title suggestion to mark as selected."),
        quantityOverrides: z
          .array(QuantityOverrideSchema)
          .optional()
          .describe("Optional model-reviewed SKU quantity overrides for ambiguous SKU names."),
      },
    },
    async ({ recordId, unitPrice, enhanced, useTrending, titleIndex, quantityOverrides }) =>
      buildPreparationDraft(recordId, unitPrice, {
        enhanced: enhanced ?? true,
        useTrending: useTrending ?? true,
        titleIndex: titleIndex ?? 0,
        quantityOverrides: quantityOverrides ?? [],
      })
  );

  registerTool(
    server,
    "apply_preparation_draft",
    {
      description:
        "Apply generated title and/or smart prices to a product, then return the updated product and upload-readiness state.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z.number().positive().describe("Base cost per pair of socks."),
        enhanced: z.boolean().optional().describe("Use enhanced title generation."),
        useTrending: z
          .boolean()
          .optional()
          .describe("Whether enhanced title generation should load trending keywords."),
        title: z.string().optional().describe("Explicit title to apply instead of a generated suggestion."),
        titleIndex: z
          .number()
          .int()
          .min(0)
          .optional()
          .describe("If title is not provided, which generated title suggestion to apply."),
        applyTitle: z.boolean().optional().describe("Whether to apply a title change."),
        applyPrices: z.boolean().optional().describe("Whether to apply smart prices."),
        quantityOverrides: z
          .array(QuantityOverrideSchema)
          .optional()
          .describe("Optional model-reviewed SKU quantity overrides for ambiguous SKU names."),
      },
    },
    async ({
      recordId,
      unitPrice,
      enhanced,
      useTrending,
      title,
      titleIndex,
      applyTitle,
      applyPrices,
      quantityOverrides,
    }) => {
      const shouldApplyTitle = applyTitle ?? true;
      const shouldApplyPrices = applyPrices ?? true;

      if (!shouldApplyTitle && !shouldApplyPrices) {
        throw new Error("At least one of applyTitle or applyPrices must be true.");
      }

      const draft = await buildPreparationDraft(recordId, unitPrice, {
        enhanced: enhanced ?? true,
        useTrending: useTrending ?? true,
        titleIndex: titleIndex ?? 0,
        quantityOverrides: quantityOverrides ?? [],
      });

      const updates = {};
      if (shouldApplyTitle) {
        const chosenTitle = title ?? draft?.title_generation?.selected_title;
        if (!chosenTitle) {
          throw new Error("No title was available to apply.");
        }
        updates.title = chosenTitle;
      }

      if (shouldApplyPrices) {
        updates.skuUpdates = draft?.draft_updates?.sku_updates || [];
      }

      const persisted = await persistProductChanges(recordId, updates);
      const readinessAfterApply = persisted.product
        ? await buildUploadReadiness(recordId, persisted.product)
        : null;
      return {
        applied: {
          title_applied: updates.title ?? null,
          price_update_count: (updates.skuUpdates || []).length,
        },
        draft,
        updated_product: persisted.product,
        validation_after_apply: readinessAfterApply,
        save: persisted.save,
      };
    }
  );

  registerTool(
    server,
    "update_product_info",
    {
      description:
        "Update product title, remark, category, repo, or selected SKU names/prices. This tool hides the legacy save_info payload shape.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        title: z.string().optional().describe("New product title."),
        remark: z.string().optional().describe("New product remark."),
        repo: z.number().nullable().optional().describe("Inventory or repo value."),
        clazz: z
          .number()
          .int()
          .min(0)
          .max(4)
          .nullable()
          .optional()
          .describe("Product category code."),
        skuUpdates: z
          .array(
            z.object({
              path: z.string().min(1).describe("Exact SKU path."),
              name: z.string().optional().describe("Updated SKU display name."),
              price: z.number().nonnegative().optional().describe("Updated SKU price."),
            })
          )
          .optional()
          .describe("Partial SKU updates keyed by SKU path."),
      },
    },
    async (args) => persistProductChanges(args.recordId, args)
  );

  registerTool(
    server,
    "set_product_category",
    {
      description:
        "Set one product category by numeric code or human-readable label, then return the updated product.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        categoryValue: z.number().int().min(0).max(4).optional().describe("Category code."),
        categoryLabel: z.string().optional().describe("Category label such as 船袜 or 中筒袜."),
      },
    },
    async ({ recordId, categoryValue, categoryLabel }) => {
      const category = resolveCategoryOption({ categoryValue, categoryLabel });
      const persisted = await persistProductChanges(recordId, {
        clazz: category.value,
      });

      return {
        category,
        updated_product: persisted.product,
        save: persisted.save,
      };
    }
  );

  registerTool(
    server,
    "delete_sku",
    {
      description: "Delete one SKU from a product by exact SKU path.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        skuPath: z.string().min(1).describe("Exact SKU path to delete."),
      },
    },
    async ({ recordId, skuPath }) => deleteSku(recordId, skuPath)
  );

  registerTool(
    server,
    "delete_product",
    {
      description: "Delete one product from the local database.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
      },
    },
    async ({ recordId }) => deleteProduct(recordId)
  );

  registerTool(
    server,
    "delete_all_products",
    {
      description: "Delete all products from the local database. This is destructive.",
    },
    async () => deleteAllProducts()
  );

  registerTool(
    server,
    "open_product_folder",
    {
      description: "Open the local product folder in the operating system file explorer.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
      },
    },
    async ({ recordId }) => openProductFolder(recordId)
  );

  registerTool(
    server,
    "import_product_folders",
    {
      description:
        "Import one or more local product folders into the app database. Paths should point to product directories on disk.",
      inputSchema: {
        paths: z
          .array(z.string().min(1))
          .min(1)
          .describe("Absolute folder paths to import."),
      },
    },
    async ({ paths }) =>
      backendRequest("/api/import/folders", {
        method: "POST",
        body: { paths },
      })
  );

  registerTool(
    server,
    "analyze_sku_quantities",
    {
      description:
        "Inspect every SKU name and image with the current rule-based quantity inference so a model can review and override ambiguous pair counts.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        includeBase64: z
          .boolean()
          .optional()
          .describe("Whether to include base64-encoded SKU image content."),
      },
    },
    async ({ recordId, includeBase64 }) =>
      analyzeSkuQuantities(recordId, {
        includeBase64: includeBase64 ?? false,
      })
  );

  registerTool(
    server,
    "generate_smart_title",
    {
      description:
        "Generate title suggestions for a product. Use enhanced=true to include trending keywords.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        enhanced: z.boolean().optional().describe("Use the enhanced title flow."),
        useTrending: z
          .boolean()
          .optional()
          .describe("Whether enhanced generation should load trending keywords."),
      },
    },
    async ({ recordId, enhanced, useTrending }) =>
      fetchTitleSuggestions(recordId, {
        enhanced: enhanced ?? false,
        useTrending: useTrending ?? true,
      })
  );

  registerTool(
    server,
    "calculate_smart_prices",
    {
      description:
        "Calculate smart prices for all SKUs in a product based on a unit sock cost.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        unitPrice: z.number().positive().describe("Base cost per pair of socks."),
        quantityOverrides: z
          .array(QuantityOverrideSchema)
          .optional()
          .describe("Optional model-reviewed SKU quantity overrides for ambiguous SKU names."),
      },
    },
    async ({ recordId, unitPrice, quantityOverrides }) =>
      getSmartPricingPayload(recordId, unitPrice, {
        quantityOverrides: quantityOverrides ?? [],
      })
  );

  registerTool(
    server,
    "start_capture",
    {
      description:
        "Start a Taobao, Tmall, or 1688 product capture task in the local app.",
      inputSchema: {
        url: z.string().url().describe("Source product URL."),
        options: z
          .record(z.string(), z.unknown())
          .optional()
          .describe("Optional capture parameters."),
      },
    },
    async ({ url, options }) =>
      normalizeCaptureResponse(await backendRequest("/api/capture/start", {
        method: "POST",
        body: { url, options: options ?? {} },
      }))
  );

  registerTool(
    server,
    "start_capture_batch",
    {
      description:
        "Start capture tasks for multiple Taobao, Tmall, or 1688 product links in one call.",
      inputSchema: {
        urls: z.array(z.string().url()).min(1).describe("Source product URLs."),
        options: z
          .record(z.string(), z.unknown())
          .optional()
          .describe("Optional capture parameters applied to every URL."),
        stopOnError: z
          .boolean()
          .optional()
          .describe("Stop launching later URLs after the first failure."),
      },
    },
    async ({ urls, options, stopOnError }) =>
      startCaptureBatch(urls, {
        captureOptions: options ?? {},
        stopOnError: stopOnError ?? false,
      })
  );

  registerTool(
    server,
    "get_capture_status",
    {
      description: "Read the current status of a capture task.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        taskId: z.string().min(1).describe("Capture task ID."),
      },
    },
    async ({ taskId }) => backendRequest(`/api/capture/status/${taskId}`)
  );

  registerTool(
    server,
    "import_capture_result",
    {
      description: "Import a completed capture task into the product database.",
      inputSchema: {
        taskId: z.string().min(1).describe("Capture task ID."),
        category: z.number().int().min(0).max(4).optional().describe("Target product category."),
      },
    },
    async ({ taskId, category }) =>
      backendRequest("/api/capture/import", {
        method: "POST",
        body: {
          task_id: taskId,
          category: category ?? 1,
        },
      })
  );

  registerTool(
    server,
    "cancel_capture",
    {
      description: "Cancel a running capture task.",
      inputSchema: {
        taskId: z.string().min(1).describe("Capture task ID."),
      },
    },
    async ({ taskId }) =>
      backendRequest(`/api/capture/cancel/${taskId}`, {
        method: "POST",
      })
  );

  registerTool(
    server,
    "get_capture_history",
    {
      description: "List recent capture tasks known to the local app.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/capture/history")
  );

  registerTool(
    server,
    "start_upload",
    {
      description:
        "Start an upload task for one product or, if allProducts=true, for all ready products.",
      inputSchema: {
        recordId: z.number().int().positive().optional().describe("Single product record ID."),
        allProducts: z.boolean().optional().describe("Set true to start the legacy all-products upload flow."),
        stopBeforeSubmit: z
          .boolean()
          .optional()
          .describe("Set true for a safe preflight that stops before the final publish/submit action."),
        confirmFinalPublish: z
          .boolean()
          .optional()
          .describe("Must be true with stopBeforeSubmit=false for final publish."),
      },
    },
    async ({ recordId, allProducts, stopBeforeSubmit, confirmFinalPublish }) => {
      const request = buildUploadStartRequest({
        recordId,
        allProducts,
        stopBeforeSubmit,
        confirmFinalPublish,
      });
      return backendRequest(request.path, {
        method: "POST",
        body: request.body,
      });
    }
  );

  registerTool(
    server,
    "start_validated_upload",
    {
      description:
        "Validate a product first, and only start upload if the product is currently upload-ready, including required local media assets.",
      inputSchema: {
        recordId: z.number().int().positive().describe("Product record ID."),
        stopBeforeSubmit: z
          .boolean()
          .optional()
          .describe("Set true for upload preflight; the browser automation stops before final publish/submit."),
        confirmFinalPublish: z
          .boolean()
          .optional()
          .describe("Must be true with stopBeforeSubmit=false for final publish."),
      },
    },
    async ({ recordId, stopBeforeSubmit, confirmFinalPublish }) => {
      const validation = await buildUploadReadiness(recordId);
      if (!validation.ready) {
        return {
          started: false,
          validation,
          message: "Upload was not started because the product is not ready.",
        };
      }

      const request = buildUploadStartRequest({ recordId, stopBeforeSubmit, confirmFinalPublish });
      const upload = await backendRequest(request.path, {
        method: "POST",
        body: request.body,
      });

      return {
        started: true,
        validation,
        stop_before_submit: request.body.stop_before_submit,
        final_publish_confirmed: Boolean(request.body.confirm_final_publish),
        upload,
      };
    }
  );

  registerTool(
    server,
    "get_upload_status",
    {
      description: "Read the current status of an upload task.",
      annotations: { readOnlyHint: true },
      inputSchema: {
        taskId: z.string().min(1).describe("Upload task ID."),
      },
    },
    async ({ taskId }) => backendRequest(`/api/upload/status/${taskId}`)
  );

  registerTool(
    server,
    "list_upload_tasks",
    {
      description: "List all upload tasks and the browser automation status.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/api/upload/tasks")
  );

  registerTool(
    server,
    "ensure_upload_browser",
    {
      description:
        "Ensure the publish/upload browser session exists and is logged in, without starting an upload task.",
    },
    async () =>
      backendRequest("/api/upload/ensure-session", {
        method: "POST",
      })
  );

  registerTool(
    server,
    "cancel_upload",
    {
      description: "Cancel a running upload task.",
      inputSchema: {
        taskId: z.string().min(1).describe("Upload task ID."),
      },
    },
    async ({ taskId }) =>
      backendRequest(`/api/upload/cancel/${taskId}`, {
        method: "POST",
      })
  );

  registerTool(
    server,
    "start_batch_upload",
    {
      description: "Create upload tasks for multiple products and start the first one.",
      inputSchema: {
        recordIds: z
          .array(z.number().int().positive())
          .min(1)
          .describe("Product record IDs to enqueue."),
      },
    },
    async ({ recordIds }) =>
      backendRequest("/api/upload/batch", {
        method: "POST",
        body: { record_ids: recordIds },
      })
  );
}

export function createDouyinPublisherServer() {
  const server = new McpServer({
    name: "douyin-publisher",
    version: "1.3.0",
  });

  registerCoreTools(server);
  registerCdpTools(server);
  registerResources(server);
  registerPrompts(server);

  return server;
}

export function getConfiguredBackendUrl() {
  return getBackendBaseUrl();
}
