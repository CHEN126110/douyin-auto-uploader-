import fs from "node:fs/promises";
import path from "node:path";

import { probeFxgUploadEndpoints } from "../fxg-upload-probe.js";

const outputPath = process.env.OUTPUT_PATH || "";

const result = await probeFxgUploadEndpoints({
  cdpListUrl: process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL,
  targetUrlContains: process.env.TARGET_HINT,
  maxModules: process.env.MAX_MODULES,
  uploadImagePath: process.env.UPLOAD_IMAGE_PATH,
  uploadImagePaths: String(process.env.UPLOAD_IMAGE_PATHS || "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean),
  uploadMode: process.env.UPLOAD_MODE,
  uploadFileName: process.env.UPLOAD_FILE_NAME,
  uploadFileNames: String(process.env.UPLOAD_FILE_NAMES || "")
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean),
});

if (outputPath) {
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
}

console.log(JSON.stringify(result, null, 2));
