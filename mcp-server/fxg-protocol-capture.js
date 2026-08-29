import { delay, normalizeCdpListUrl, withCdpTarget } from "./cdp-client.js";

export const DEFAULT_FXG_TARGET_HINT = "fxg.jinritemai.com/ffa/g/create";

const DEFAULT_URL_PATTERNS = [
  "/product/img/batchupload",
  "/product/tproduct/saveMaterial",
  "/product/tproduct/materialDetail",
  "/product/tproduct/material/batchApplyMaterial",
  "/product/tproduct/submitWhiteImg",
  "/product/tproduct/batchApprovalWhiteImgs",
  "/product/tproduct/addWithSchema",
  "/product/tproduct/editWithSchema",
  "/common/img/IsWhiteBackgroundPic",
  "/ffa/grs/qualification/list",
  "/ffa/mshop/qualification/list",
];

const CAPTURE_PROFILES = {
  "submit-preflight": {
    description: "Block local publish-write requests and collect request bodies before they reach FXG.",
    urlPatterns: DEFAULT_URL_PATTERNS,
    blockMatchedRequests: true,
  },
  "submit-only": {
    description: "Block addWithSchema/editWithSchema and collect final submit request bodies.",
    urlPatterns: ["/product/tproduct/addWithSchema", "/product/tproduct/editWithSchema"],
    blockMatchedRequests: true,
  },
  "media-preflight": {
    description: "Block media/material related write requests and collect image/detail request bodies.",
    urlPatterns: [
      "/product/img/batchupload",
      "/product/tproduct/saveMaterial",
      "/product/tproduct/materialDetail",
      "/product/tproduct/material/batchApplyMaterial",
      "/product/tproduct/submitWhiteImg",
      "/product/tproduct/batchApprovalWhiteImgs",
      "/common/img/IsWhiteBackgroundPic",
    ],
    blockMatchedRequests: true,
  },
};

function parseBoolean(value) {
  if (value === true) return true;
  return /^(1|true|yes|on)$/i.test(String(value || "").trim());
}

function parsePatternList(value) {
  if (Array.isArray(value)) {
    return value.map((item) => String(item).trim()).filter(Boolean);
  }
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeOptions(options = {}) {
  const captureProfile = String(options.captureProfile || process.env.CAPTURE_PROFILE || "").trim();
  const profile = CAPTURE_PROFILES[captureProfile] || null;
  const explicitUrlPatterns = parsePatternList(options.urlPatterns);
  const envUrlPatterns = parsePatternList(process.env.URL_PATTERNS);
  const urlPatterns = explicitUrlPatterns.length > 0 ? explicitUrlPatterns : envUrlPatterns;
  const blockUrlPatterns =
    parsePatternList(options.blockUrlPatterns).length > 0
      ? parsePatternList(options.blockUrlPatterns)
      : parsePatternList(process.env.BLOCK_URL_PATTERNS);
  const hasExplicitBlockMode =
    Object.prototype.hasOwnProperty.call(options, "blockMatchedRequests") ||
    String(process.env.BLOCK_MATCHED_REQUESTS || "").trim() !== "";

  return {
    captureProfile: profile ? captureProfile : "",
    captureProfileDescription: profile?.description || "",
    cdpListUrl: options.cdpListUrl || process.env.DOUYIN_CDP_LIST_URL || process.env.CDP_LIST_URL,
    targetUrlContains: options.targetUrlContains || process.env.TARGET_HINT || DEFAULT_FXG_TARGET_HINT,
    durationMs: Number(options.durationMs || process.env.DURATION_MS || 15000),
    maxEntries: Number(options.maxEntries || process.env.MAX_ENTRIES || 80),
    postDataPreviewLimit: Number(options.postDataPreviewLimit || process.env.POST_DATA_PREVIEW_LIMIT || 12000),
    sanitizeMaxDepth: Number(options.sanitizeMaxDepth || process.env.SANITIZE_MAX_DEPTH || 5),
    sanitizeStringLimit: Number(options.sanitizeStringLimit || process.env.SANITIZE_STRING_LIMIT || 1000),
    sanitizeArrayLimit: Number(options.sanitizeArrayLimit || process.env.SANITIZE_ARRAY_LIMIT || 30),
    sanitizeObjectLimit: Number(options.sanitizeObjectLimit || process.env.SANITIZE_OBJECT_LIMIT || 120),
    includeResponseBody: options.includeResponseBody === true || process.env.INCLUDE_RESPONSE_BODY === "true",
    responseBodyLimit: Number(options.responseBodyLimit || process.env.RESPONSE_BODY_LIMIT || 12000),
    urlPatterns: urlPatterns.length > 0 ? urlPatterns : profile?.urlPatterns || DEFAULT_URL_PATTERNS,
    blockMatchedRequests: hasExplicitBlockMode
      ? parseBoolean(options.blockMatchedRequests) || parseBoolean(process.env.BLOCK_MATCHED_REQUESTS)
      : Boolean(profile?.blockMatchedRequests),
    blockUrlPatterns: blockUrlPatterns.length > 0 ? blockUrlPatterns : profile?.urlPatterns || [],
    blockedErrorReason: options.blockedErrorReason || process.env.BLOCKED_ERROR_REASON || "Aborted",
  };
}

function truncateText(value, maxLength) {
  if (value == null) return value;
  const text = String(value);
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...<truncated ${text.length - maxLength} chars>`;
}

function sanitizeUrl(value) {
  if (!value) return value;
  const text = String(value);
  try {
    if (!/^https?:\/\//i.test(text) && !text.startsWith("/")) {
      throw new Error("not-url-like");
    }
    const parsed = new URL(text, "https://fxg.jinritemai.com");
    for (const key of Array.from(parsed.searchParams.keys())) {
      if (/token|msToken|a_bogus|verify|fp|sign|auth|cookie/i.test(key)) {
        parsed.searchParams.set(key, "<redacted>");
      }
    }
    return parsed.toString();
  } catch (_) {
    return text
      .replace(/__token=[^"'&]+/g, "__token=<redacted>")
      .replace(/msToken=[^"'&]+/g, "msToken=<redacted>")
      .replace(/a_bogus=[^"'&]+/g, "a_bogus=<redacted>");
  }
}

function summarizeUrl(value) {
  try {
    const parsed = new URL(value, "https://fxg.jinritemai.com");
    return {
      origin: parsed.origin,
      path: parsed.pathname,
      queryKeys: Array.from(parsed.searchParams.keys()),
      sanitized: sanitizeUrl(value),
    };
  } catch (_) {
    return {
      origin: "",
      path: "",
      queryKeys: [],
      sanitized: sanitizeUrl(value),
    };
  }
}

function sanitizeValue(value, limits, depth = 0) {
  if (depth > limits.maxDepth) return "<max-depth>";
  if (value == null) return value;
  if (typeof value === "string") return truncateText(sanitizeUrl(value), limits.stringLimit);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (Array.isArray(value)) {
    return value.slice(0, limits.arrayLimit).map((item) => sanitizeValue(item, limits, depth + 1));
  }
  if (typeof value === "object") {
    const result = {};
    for (const [key, item] of Object.entries(value).slice(0, limits.objectLimit)) {
      if (/cookie|token|authorization|mobile|phone|password|secret|session|sign/i.test(key)) {
        result[key] = "<redacted>";
      } else {
        result[key] = sanitizeValue(item, limits, depth + 1);
      }
    }
    return result;
  }
  return "<unsupported>";
}

function sanitizePostData(postData, previewLimit, limits) {
  if (!postData) return undefined;
  const text = String(postData);
  const normalizedText = text.replace(/\r\n/g, "\n");
  const maybeBase64 =
    text.length >= 32 &&
    text.length % 4 === 0 &&
    /^[A-Za-z0-9+/=\r\n]+$/.test(text) &&
    !/[{}[\]":;]/.test(text);

  if (!/Content-Disposition:\s*form-data;/i.test(normalizedText) && maybeBase64) {
    try {
      const decoded = Buffer.from(text, "base64").toString("utf8");
      if (/Content-Disposition:\s*form-data;/i.test(decoded)) {
        return sanitizePostData(decoded, previewLimit, limits);
      }
      return {
        type: "base64",
        preview: truncateText(decoded, previewLimit),
      };
    } catch (_) {
      // Ignore and continue.
    }
  }
  try {
    const sanitized = sanitizeValue(JSON.parse(text), limits);
    return {
      type: "json",
      value: sanitized,
      preview: truncateText(JSON.stringify(sanitized), previewLimit),
    };
  } catch (_) {
    // Continue with form/urlencoded/plain processing.
  }

  if (/Content-Disposition:\s*form-data;/i.test(normalizedText)) {
    const boundaryLine = normalizedText.split("\n", 1)[0] || "";
    const boundary = boundaryLine.startsWith("--") ? boundaryLine : "";
    const rawParts = boundary ? normalizedText.split(boundary).slice(1, -1) : [];
    const parts = rawParts
      .map((part) => part.replace(/^\n/, "").replace(/\n$/, ""))
      .filter(Boolean)
      .map((part) => {
        const [rawHeaders, ...bodyParts] = part.split("\n\n");
        const headers = rawHeaders || "";
        const body = bodyParts.join("\n\n").replace(/\n$/, "");
        const nameMatch = headers.match(/name="([^"]+)"/i);
        const fileNameMatch = headers.match(/filename="([^"]+)"/i);
        const contentTypeMatch = headers.match(/Content-Type:\s*([^\n]+)/i);
        const fieldName = nameMatch ? nameMatch[1] : "";
        const fileName = fileNameMatch ? fileNameMatch[1] : "";
        const contentType = contentTypeMatch ? contentTypeMatch[1] : "";
        const isBinary = Boolean(fileName) || /image|video|octet-stream|application\/zip/i.test(contentType);

        let textPreview = undefined;
        let parsedValue = undefined;
        if (!isBinary && body) {
          const bodyTrimmed = body.trim();
          try {
            parsedValue = sanitizeValue(JSON.parse(bodyTrimmed), limits);
          } catch (_) {
            parsedValue = truncateText(sanitizeUrl(bodyTrimmed), limits.stringLimit);
          }
          textPreview =
            typeof parsedValue === "string"
              ? truncateText(parsedValue, 500)
              : truncateText(JSON.stringify(parsedValue), 500);
        }

        return {
          fieldName,
          fileName: fileName || undefined,
          contentType: contentType || undefined,
          sizeBytes: body.length,
          binaryOmitted: isBinary || undefined,
          value: parsedValue,
          preview: textPreview,
        };
      });

    return {
      type: "multipart",
      partCount: parts.length,
      value: parts,
      preview: truncateText(JSON.stringify(parts), previewLimit),
    };
  }

  if (text.includes("=") && !text.includes("\r\nContent-Disposition")) {
    try {
      const params = new URLSearchParams(text);
      const value = {};
      for (const [key, item] of params.entries()) {
        value[key] = /token|cookie|auth|sign|password|secret/i.test(key) ? "<redacted>" : truncateText(sanitizeUrl(item), limits.stringLimit);
      }
      return {
        type: "form",
        value,
        preview: truncateText(JSON.stringify(value), previewLimit),
      };
    } catch (_) {
      // Fall through.
    }
  }

  return {
    type: text.includes("\r\nContent-Disposition") ? "multipart" : "text",
    value: undefined,
    preview: truncateText(sanitizeUrl(text), previewLimit),
  };
}

function matchesAny(url, patterns) {
  return patterns.some((pattern) => url.includes(pattern));
}

function toFetchUrlPattern(pattern) {
  const text = String(pattern || "").trim();
  if (!text) return "";
  return text.includes("*") ? text : `*${text}*`;
}

function classifyEndpoint(path) {
  if (path.includes("/product/tproduct/addWithSchema") || path.includes("/product/tproduct/editWithSchema")) {
    return ["final_submit", "sku_price_stock", "detail_page", "qualification"];
  }
  if (path.includes("/product/img/batchupload")) {
    return ["image_upload", "detail_page", "qualification"];
  }
  if (
    path.includes("/product/tproduct/saveMaterial") ||
    path.includes("/product/tproduct/materialDetail") ||
    path.includes("/product/tproduct/material/batchApplyMaterial")
  ) {
    return ["image_upload", "detail_page"];
  }
  if (path.includes("/product/tproduct/submitWhiteImg") || path.includes("/product/tproduct/batchApprovalWhiteImgs")) {
    return ["image_upload"];
  }
  if (path.includes("/common/img/IsWhiteBackgroundPic")) {
    return ["image_upload"];
  }
  if (path.includes("/ffa/grs/qualification/list") || path.includes("/ffa/mshop/qualification/list")) {
    return ["qualification"];
  }
  return ["other"];
}

function buildEvidenceSummary(entries, blockFailureCount = 0) {
  const chains = {
    final_submit: [],
    sku_price_stock: [],
    image_upload: [],
    detail_page: [],
    qualification: [],
    other: [],
  };
  for (const entry of entries) {
    const path = entry?.url?.path || "";
    for (const chain of classifyEndpoint(path)) {
      chains[chain].push({
        method: entry.method,
        path,
        blocked: Boolean(entry.blocked),
        hasPostData: Boolean(entry.hasPostData),
        postDataType: entry.postData?.type || "",
      });
    }
  }

  const targetStatus = Object.fromEntries(
    Object.entries(chains).map(([chain, items]) => [
      chain,
      {
        requestCount: items.length,
        blockedCount: items.filter((item) => item.blocked).length,
        hasRequestBody: items.some((item) => item.hasPostData),
        endpoints: Array.from(new Set(items.map((item) => item.path).filter(Boolean))),
      },
    ])
  );

  return {
    targetStatus,
    requestedEvidence: {
      addWithSchema: targetStatus.final_submit,
      skuPriceStock: targetStatus.sku_price_stock,
      imageUpload: targetStatus.image_upload,
      detailImages: targetStatus.detail_page,
      qualification: targetStatus.qualification,
    },
    note:
      blockFailureCount > 0
        ? `Summary is derived from sanitized local capture entries. Blocked entries were aborted before reaching the server, but ${blockFailureCount} matched request(s) could NOT be aborted and are not counted as blocked; see blockFailures and the per-entry blockAbortError field.`
        : "Summary is derived from sanitized local capture entries. Blocked entries were aborted before reaching the server.",
  };
}

export async function captureFxgProtocolRequests(options = {}) {
  const normalized = normalizeOptions(options);
  const durationMs = Math.max(1000, Math.min(normalized.durationMs, 300000));
  const maxEntries = Math.max(1, Math.min(normalized.maxEntries, 200));
  const postDataPreviewLimit = Math.max(200, Math.min(normalized.postDataPreviewLimit, 50000));
  const sanitizeLimits = {
    maxDepth: Math.max(1, Math.min(normalized.sanitizeMaxDepth, 12)),
    stringLimit: Math.max(50, Math.min(normalized.sanitizeStringLimit, 4000)),
    arrayLimit: Math.max(1, Math.min(normalized.sanitizeArrayLimit, 120)),
    objectLimit: Math.max(1, Math.min(normalized.sanitizeObjectLimit, 300)),
  };
  const responseBodyLimit = Math.max(200, Math.min(normalized.responseBodyLimit, 50000));
  const blockUrlPatterns = normalized.blockUrlPatterns.length > 0 ? normalized.blockUrlPatterns : normalized.urlPatterns;
  const shouldBlockMatchedRequests = normalized.blockMatchedRequests && blockUrlPatterns.length > 0;

  return withCdpTarget(
    {
      cdpListUrl: normalized.cdpListUrl,
      targetUrlContains: normalized.targetUrlContains,
    },
    async (client, target) => {
      const entries = [];
      const entriesByRequestId = new Map();
      const postDataTasks = new Map();
      const responseBodyTasks = new Map();
      const blockedNetworkRequestIds = new Set();
      const blockedRequestKeys = new Set();
      const handlerErrors = [];
      let blockFailureCount = 0;

      async function handlePausedRequest(params) {
        const req = params.request || {};
        if (!req.url || !matchesAny(req.url, blockUrlPatterns)) {
          await client.call("Fetch.continueRequest", { requestId: params.requestId });
          return;
        }

        const requestKey = `${req.method || "GET"} ${req.url}`;
        blockedRequestKeys.add(requestKey);
        if (params.networkId) blockedNetworkRequestIds.add(params.networkId);

        let blockedEntry = null;
        if (entries.length < maxEntries) {
          const entry = {
            requestId: params.networkId || params.requestId,
            fetchRequestId: params.requestId,
            method: req.method || "GET",
            resourceType: params.resourceType,
            url: summarizeUrl(req.url),
            hasPostData: Boolean(req.postData),
            postData: sanitizePostData(req.postData, postDataPreviewLimit, sanitizeLimits),
            intercepted: true,
            blocked: true,
            blockedErrorReason: normalized.blockedErrorReason,
          };
          entries.push(entry);
          blockedEntry = entry;
          if (params.networkId) entriesByRequestId.set(params.networkId, entry);
        }

        try {
          await client.call("Fetch.failRequest", {
            requestId: params.requestId,
            errorReason: normalized.blockedErrorReason,
          });
        } catch (error) {
          // The abort did not happen: the request stays paused and Chrome releases it
          // once Fetch is disabled, so it may still reach the server. Report it as such
          // instead of leaving the entry marked as blocked.
          const message = error instanceof Error ? error.message : String(error);
          blockFailureCount += 1;
          if (blockedEntry) {
            blockedEntry.blocked = false;
            blockedEntry.blockAbortError = message;
          }
          handlerErrors.push({
            phase: "Fetch.failRequest",
            method: req.method || "GET",
            url: sanitizeUrl(req.url),
            error: message,
          });
        }
      }

      const off = client.onEvent((method, params) => {
        if (method === "Fetch.requestPaused") {
          handlePausedRequest(params).catch((error) => {
            // Keep capture alive even if Chrome rejects a paused request operation,
            // but never swallow the failure: report it with the capture result.
            handlerErrors.push({
              phase: "Fetch.requestPaused",
              url: sanitizeUrl(params?.request?.url || ""),
              error: error instanceof Error ? error.message : String(error),
            });
          });
          return;
        }

        if (method === "Network.requestWillBeSent") {
          const req = params.request;
          if (!req?.url || !matchesAny(req.url, normalized.urlPatterns)) return;
          if (blockedNetworkRequestIds.has(params.requestId)) return;
          if (blockedRequestKeys.has(`${req.method || "GET"} ${req.url}`)) return;
          if (entries.length >= maxEntries) return;

          const url = summarizeUrl(req.url);
          const entry = {
            requestId: params.requestId,
            method: req.method || "GET",
            resourceType: params.type,
            url,
            hasPostData: Boolean(req.hasPostData || req.postData),
            postData: sanitizePostData(req.postData, postDataPreviewLimit, sanitizeLimits),
          };
          entries.push(entry);
          entriesByRequestId.set(params.requestId, entry);

          if (req.hasPostData && !postDataTasks.has(params.requestId)) {
            const task = client
              .call("Network.getRequestPostData", { requestId: params.requestId })
              .then((result) => {
                entry.postData = sanitizePostData(result?.postData || req.postData || "", postDataPreviewLimit, sanitizeLimits);
              })
              .catch((error) => {
                entry.postDataError = error instanceof Error ? error.message : String(error);
              })
              .finally(() => postDataTasks.delete(params.requestId));
            postDataTasks.set(params.requestId, task);
          }
          return;
        }

        if (method === "Network.responseReceived") {
          const entry = entriesByRequestId.get(params.requestId);
          if (!entry) return;
          entry.status = params.response?.status ?? null;
          entry.mimeType = params.response?.mimeType || "";
          return;
        }

        if (method === "Network.loadingFinished" && normalized.includeResponseBody) {
          const entry = entriesByRequestId.get(params.requestId);
          if (!entry || responseBodyTasks.has(params.requestId)) return;
          const task = client
            .call("Network.getResponseBody", { requestId: params.requestId })
            .then((result) => {
              if (result?.base64Encoded) {
                entry.responseBodyPreview = "[base64 body omitted]";
                return;
              }
              entry.responseBodyPreview = truncateText(sanitizeUrl(result?.body || ""), responseBodyLimit);
            })
            .catch((error) => {
              entry.responseBodyError = error instanceof Error ? error.message : String(error);
            })
            .finally(() => responseBodyTasks.delete(params.requestId));
          responseBodyTasks.set(params.requestId, task);
        }
      });

      try {
        if (shouldBlockMatchedRequests) {
          await client.call("Fetch.enable", {
            patterns: blockUrlPatterns.map((pattern) => ({
              urlPattern: toFetchUrlPattern(pattern),
              requestStage: "Request",
            })),
          });
        }
        await client.call("Network.enable", {
          maxTotalBufferSize: 10000000,
          maxResourceBufferSize: 5000000,
          maxPostDataSize: 10 * 1024 * 1024,
        });
        await delay(durationMs);
        if (postDataTasks.size > 0) {
          await Promise.allSettled(Array.from(postDataTasks.values()));
        }
        if (responseBodyTasks.size > 0) {
          await Promise.allSettled(Array.from(responseBodyTasks.values()));
        }
      } finally {
        if (shouldBlockMatchedRequests) {
          await client.call("Fetch.disable").catch(() => {});
        }
        off();
      }

      return {
        ok: true,
        captureProfile: normalized.captureProfile || undefined,
        captureProfileDescription: normalized.captureProfileDescription || undefined,
        cdpListUrl: normalizeCdpListUrl(normalized.cdpListUrl),
        target: {
          id: target.id,
          title: target.title,
          url: target.url,
        },
        durationMs,
        urlPatterns: normalized.urlPatterns,
        blockMatchedRequests: shouldBlockMatchedRequests,
        blockUrlPatterns: shouldBlockMatchedRequests ? blockUrlPatterns : [],
        blockedCount: entries.filter((entry) => entry.blocked).length,
        blockFailures: blockFailureCount,
        handlerErrors,
        count: entries.length,
        evidenceSummary: buildEvidenceSummary(entries, blockFailureCount),
        requests: entries,
        note: shouldBlockMatchedRequests
          ? blockFailureCount > 0
            ? `Targeted protocol capture with sanitized URLs and bodies. BLOCKING FAILED for ${blockFailureCount} matched request(s): Fetch.failRequest was rejected, so those requests were NOT aborted and may have reached the server. See blockFailures and the per-entry blockAbortError field.`
            : "Targeted protocol capture with sanitized URLs and bodies. Matched blockUrlPatterns were aborted before reaching the server."
          : "Targeted protocol capture with sanitized URLs and bodies. It only observes page traffic during the capture window.",
      };
    }
  );
}
