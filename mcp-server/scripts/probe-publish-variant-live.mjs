// 只读：把 app.py 里的**生产 JS 原文**取出来，在真实发布页上复算形态判定。
//
// 为什么需要在真实页面上复算：形态判定的正确性只取决于「这段 JS 在目标 DOM 上返回什么」。
// 单测只能证明源码里有某些字符串，证明不了它判得对。这个探针补上那一环。
//
// 红线：只做 Runtime.evaluate 读取，不点击、不输入、不上传、不保存、不提交。
//
// 用法：
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9500/json/list'
//   node mcp-server/scripts/probe-publish-variant-live.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const APP = path.join(ROOT, "tauri-app", "python-sidecar", "app.py");
const SRC = readFileSync(APP, "utf8");

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";

function extractRawJs(name) {
  const re = new RegExp(name + "\\s*=\\s*r'''([\\s\\S]*?)'''");
  const m = SRC.match(re);
  if (!m) throw new Error("app.py 里找不到 " + name);
  return m[1];
}

function extractList(name) {
  const re = new RegExp(name + "\\s*=\\s*\\[([\\s\\S]*?)\\]");
  const m = SRC.match(re);
  if (!m) throw new Error("app.py 里找不到 " + name);
  return [...m[1].matchAll(/'([^']*)'|"([^"]*)"/g)].map((x) => x[1] ?? x[2]);
}

function extractStr(name) {
  const re = new RegExp(name + "\\s*=\\s*(['\"])(.*?)\\1");
  const m = SRC.match(re);
  if (!m) throw new Error("app.py 里找不到 " + name);
  return m[2];
}

const STAGE_JS = extractRawJs("_PUBLISH_STAGE_PROBE_JS");
const SIG_JS = extractRawJs("_PUBLISH_PAGE_SIGNATURE_JS");
const READY_JS = extractRawJs("_AI_FORM_READY_JS");
const STEP2 = extractList("_PUBLISH_STEP2_SELECTORS").map((s) => s.replace(/^xpath:/, ""));
const STEP1 = extractList("_PUBLISH_STEP1_SELECTORS").map((s) => s.replace(/^xpath:/, ""));
const AI_TEXT = extractStr("_PUBLISH_AI_CONFIRM_TEXT");
const AI_CLASS = extractStr("_PUBLISH_AI_CTA_CLASS");

const args = [STEP2, STEP1, AI_TEXT, AI_CLASS];
const STAGE_EXPR = `(function(){${STAGE_JS}})(${args.map((a) => JSON.stringify(a)).join(",")})`;
const SIG_EXPR = `(function(){${SIG_JS}})()`;
const READY_EXPR = `(function(){${READY_JS}})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
console.error(`# 命中 ${pages.length} 个目标(过滤 ${URL_FILTER})`);
console.error(`# 判定参数: aiText=${JSON.stringify(AI_TEXT)} aiClass=${JSON.stringify(AI_CLASS)} step1=${STEP1.length} 条 step2=${STEP2.length} 条`);

const results = [];
for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const evalOnce = async (expression) =>
      Promise.race([
        client.call("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }),
        delay(15000).then(() => { throw new Error("timeout"); }),
      ]);
    const stageRes = await evalOnce(STAGE_EXPR);
    const sigRes = await evalOnce(SIG_EXPR);
    const readyRes = await evalOnce(READY_EXPR);
    results.push({
      ok: !stageRes.exceptionDetails,
      url: t.url,
      stage: stageRes.exceptionDetails
        ? "(JS 抛错) " + (stageRes.exceptionDetails.exception?.description || stageRes.exceptionDetails.text)
        : stageRes.result.value,
      ready: readyRes.exceptionDetails
        ? "(JS 抛错) " + (readyRes.exceptionDetails.exception?.description || readyRes.exceptionDetails.text)
        : readyRes.result.value,
      signature: sigRes.exceptionDetails
        ? "(JS 抛错) " + (sigRes.exceptionDetails.exception?.description || sigRes.exceptionDetails.text)
        : sigRes.result.value,
    });
  } catch (e) {
    results.push({ ok: false, url: t.url, error: e instanceof Error ? e.message : String(e) });
  } finally {
    client.close();
  }
}

console.log(JSON.stringify({ listUrl: process.env.DOUYIN_CDP_LIST_URL || "(default)", results }, null, 2));
