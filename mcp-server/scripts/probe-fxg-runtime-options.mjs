import fs from "node:fs/promises";
import path from "node:path";

import { probeFxgRuntimeOptions, probeFxgRuntimeOptionsMatrix } from "../fxg-runtime-options-probe.js";

const outputPath = process.env.OUTPUT_PATH || "";
const categoryKeywords = process.env.CATEGORY_KEYWORDS || "";

const commonOptions = {
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  categoryKeyword: process.env.CATEGORY_KEYWORD,
  categoryId: process.env.CATEGORY_ID,
  operationType: process.env.OPERATION_TYPE,
  timeoutMs: process.env.TIMEOUT_MS,
  includeFreight: process.env.INCLUDE_FREIGHT !== "0",
};

const result = categoryKeywords
  ? await probeFxgRuntimeOptionsMatrix({
      ...commonOptions,
      categoryKeywords,
    })
  : await probeFxgRuntimeOptions(commonOptions);

if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
