import fs from "node:fs/promises";
import path from "node:path";

import { probeFxgFreightOptions } from "../fxg-freight-probe.js";

const outputPath = process.env.OUTPUT_PATH || "";

const result = await probeFxgFreightOptions({
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  categoryKeyword: process.env.CATEGORY_KEYWORD,
  categoryId: process.env.CATEGORY_ID,
  timeoutMs: process.env.TIMEOUT_MS,
  waitAfterActionMs: process.env.WAIT_AFTER_ACTION_MS,
  triggerAction: process.env.TRIGGER_ACTION !== "0",
});

if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
