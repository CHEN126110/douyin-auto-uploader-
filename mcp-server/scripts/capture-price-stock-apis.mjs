import fs from "node:fs/promises";
import path from "node:path";

import { buildPriceStockCaptureReport } from "../cdp-price-stock.js";
import { captureNetworkTraffic } from "../cdp-tools.js";

const OUTPUT_PATH = process.env.OUTPUT_PATH || "";
const OUTPUT_DIR = process.env.OUTPUT_DIR || "";
const CDP_LIST_URL = process.env.CDP_LIST_URL || "";
const TARGET_HINT = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";
const URL_FILTER = process.env.URL_FILTER || "jinritemai.com";
const DURATION_MS = Number(process.env.CAPTURE_MS || 15000);
const MAX_ENTRIES = Number(process.env.MAX_ENTRIES || 400);
const INCLUDE_RESPONSE_BODY = String(process.env.INCLUDE_RESPONSE_BODY || "").trim().toLowerCase() === "true";
const INCLUDE_FULL_POST_DATA = String(process.env.INCLUDE_FULL_POST_DATA || "").trim().toLowerCase() === "true";

function nowStamp() {
  const date = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}_${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
}

async function writeOutput(result) {
  let outputPath = OUTPUT_PATH;
  if (!outputPath && OUTPUT_DIR) {
    outputPath = path.join(OUTPUT_DIR, `price_stock_capture_${nowStamp()}.json`);
  }
  if (!outputPath) return null;
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
  return outputPath;
}

const capture = await captureNetworkTraffic({
  cdpListUrl: CDP_LIST_URL || undefined,
  targetUrlContains: TARGET_HINT,
  durationMs: DURATION_MS,
  urlContains: URL_FILTER,
  resourceTypes: ["XHR", "Fetch"],
  maxEntries: MAX_ENTRIES,
  dedupeByUrl: false,
  includeResponses: true,
  includeFullPostData: INCLUDE_FULL_POST_DATA,
  includeResponseBody: INCLUDE_RESPONSE_BODY,
  responseBodyLimit: 20000,
});

const result = buildPriceStockCaptureReport(capture);

const outputPath = await writeOutput(result);
if (outputPath) {
  result.outputPath = outputPath;
}

console.log(JSON.stringify(result, null, 2));
