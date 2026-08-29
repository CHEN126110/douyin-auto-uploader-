import fs from "node:fs/promises";
import path from "node:path";

import { probeFxgCategoryMatrix } from "../fxg-category-matrix-probe.js";

const outputPath = process.env.OUTPUT_PATH || "";

const result = await probeFxgCategoryMatrix({
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  categoryKeywords: process.env.CATEGORY_KEYWORDS,
  categoryIds: process.env.CATEGORY_IDS,
  optionKeywords: process.env.OPTION_KEYWORDS,
  operationType: process.env.OPERATION_TYPE,
  timeoutMs: process.env.TIMEOUT_MS,
  includeRaw: process.env.INCLUDE_RAW === "1",
});

if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
