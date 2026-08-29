/**
 * 一键启动 submit-preflight 截停：默认 CAPTURE_PROFILE、较长监听窗口、输出到项目 tmp_runtime_probe_live。
 * 在发布流程第 2 步及之后操作（保存/提交/规格/价库等）以命中 addWithSchema 等写请求；第 1 步通常只有读请求。
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.join(__dirname, "..", "..");

if (!String(process.env.CAPTURE_PROFILE || "").trim()) {
  process.env.CAPTURE_PROFILE = "submit-preflight";
}
if (!String(process.env.DURATION_MS || "").trim()) {
  process.env.DURATION_MS = "120000";
}
if (!String(process.env.POST_DATA_PREVIEW_LIMIT || "").trim()) {
  process.env.POST_DATA_PREVIEW_LIMIT = "50000";
}
if (!String(process.env.SANITIZE_MAX_DEPTH || "").trim()) {
  process.env.SANITIZE_MAX_DEPTH = "10";
}
if (!String(process.env.SANITIZE_ARRAY_LIMIT || "").trim()) {
  process.env.SANITIZE_ARRAY_LIMIT = "120";
}
if (!String(process.env.SANITIZE_OBJECT_LIMIT || "").trim()) {
  process.env.SANITIZE_OBJECT_LIMIT = "300";
}
if (!String(process.env.OUTPUT_PATH || "").trim()) {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  process.env.OUTPUT_PATH = path.join(
    projectRoot,
    "tmp_runtime_probe_live",
    `fxg_protocol_submit_preflight_${stamp}.json`,
  );
}

await import("./capture-fxg-protocol-requests.mjs");
