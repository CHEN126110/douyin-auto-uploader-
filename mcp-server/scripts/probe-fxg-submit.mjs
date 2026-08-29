import fs from "node:fs/promises";
import path from "node:path";

import { probeFxgSubmitAndSku } from "../fxg-submit-probe.js";

const outputPath = process.env.OUTPUT_PATH || "";

const result = await probeFxgSubmitAndSku({
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  maxModules: process.env.MAX_MODULES,
});

if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
