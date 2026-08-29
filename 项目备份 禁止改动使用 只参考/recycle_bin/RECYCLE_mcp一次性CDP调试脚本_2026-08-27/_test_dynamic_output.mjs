import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.join(__dirname, "..", "..");
process.env.OUTPUT_PATH = path.join(
  projectRoot,
  "tmp_runtime_probe_live",
  "_test_dynamic_output.json",
);
process.env.CAPTURE_PROFILE = "submit-preflight";
process.env.DURATION_MS = "500";
await import("./capture-fxg-protocol-requests.mjs");
const st = await fs.stat(process.env.OUTPUT_PATH);
console.log("wrote", process.env.OUTPUT_PATH, st.size);
