import fs from "node:fs/promises";
import path from "node:path";

import { captureFxgProtocolRequests } from "../fxg-protocol-capture.js";

const blockMatchedRequestsEnv = String(process.env.BLOCK_MATCHED_REQUESTS || "").trim();

const captureOptions = {
  captureProfile: process.env.CAPTURE_PROFILE,
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  durationMs: process.env.DURATION_MS,
  maxEntries: process.env.MAX_ENTRIES,
  postDataPreviewLimit: process.env.POST_DATA_PREVIEW_LIMIT,
  sanitizeMaxDepth: process.env.SANITIZE_MAX_DEPTH,
  sanitizeStringLimit: process.env.SANITIZE_STRING_LIMIT,
  sanitizeArrayLimit: process.env.SANITIZE_ARRAY_LIMIT,
  sanitizeObjectLimit: process.env.SANITIZE_OBJECT_LIMIT,
  includeResponseBody: process.env.INCLUDE_RESPONSE_BODY === "true",
  responseBodyLimit: process.env.RESPONSE_BODY_LIMIT,
  urlPatterns: String(process.env.URL_PATTERNS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
  blockUrlPatterns: String(process.env.BLOCK_URL_PATTERNS || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean),
  blockedErrorReason: process.env.BLOCKED_ERROR_REASON,
};
if (blockMatchedRequestsEnv) {
  captureOptions.blockMatchedRequests = /^(1|true|yes|on)$/i.test(blockMatchedRequestsEnv);
}

const result = await captureFxgProtocolRequests(captureOptions);

const outputPath = String(process.env.OUTPUT_PATH || "").trim();
if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
