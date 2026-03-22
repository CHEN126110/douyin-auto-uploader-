import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import fs from "node:fs/promises";
import path from "node:path";
import * as z from "zod/v4";

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

function jsonText(payload) {
  return JSON.stringify(payload, null, 2);
}

function jsonResult(payload) {
  return {
    content: [{ type: "text", text: jsonText(payload) }],
    structuredContent: payload,
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
  return backendRequest("/load_detail", {
    query: {
      _id: recordId,
      images: loadImages ? "true" : "false",
    },
  });
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

  if (manifest.counts.main_images_3_4 === 0) {
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
  if (manifest.counts.main_images_3_4 === 0) nextActions.push("Add at least one 3:4 main image.");
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
      const response = await backendRequest("/api/capture/start", {
        method: "POST",
        body: { url, options: captureOptions },
      });
      tasks.push({
        url,
        success: true,
        task_id: response?.data?.task_id ?? null,
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
              `If the product is ready and the user wants to proceed, use start_validated_upload and then poll get_upload_status.`,
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
    "get_settings",
    {
      description: "Read the current automation, pricing, and model settings from the local app.",
      annotations: { readOnlyHint: true },
    },
    async () => backendRequest("/settings")
  );

  registerTool(
    server,
    "update_settings",
    {
      description:
        "Persist settings changes to the local app. Pass only the top-level settings keys you want to update.",
      inputSchema: {
        settings: z
          .record(z.string(), z.unknown())
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
      backendRequest("/api/capture/start", {
        method: "POST",
        body: { url, options: options ?? {} },
      })
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
      },
    },
    async ({ recordId, allProducts }) => {
      if (recordId && allProducts) {
        throw new Error("Provide either recordId or allProducts=true, not both.");
      }
      if (!recordId && !allProducts) {
        throw new Error("Provide recordId for a single product upload, or allProducts=true.");
      }

      return backendRequest("/api/upload/start", {
        method: "POST",
        body: recordId ? { record_id: recordId } : {},
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
      },
    },
    async ({ recordId }) => {
      const validation = await buildUploadReadiness(recordId);
      if (!validation.ready) {
        return {
          started: false,
          validation,
          message: "Upload was not started because the product is not ready.",
        };
      }

      const upload = await backendRequest("/api/upload/start", {
        method: "POST",
        body: { record_id: recordId },
      });

      return {
        started: true,
        validation,
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
    version: "1.2.0",
  });

  registerCoreTools(server);
  registerResources(server);
  registerPrompts(server);

  return server;
}

export function getConfiguredBackendUrl() {
  return getBackendBaseUrl();
}
