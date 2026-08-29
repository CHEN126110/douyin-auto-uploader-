import fs from "node:fs/promises";
import path from "node:path";
import { CdpClient } from "../cdp-client.js";

const cdpListUrl = process.env.CDP_LIST_URL || process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
const targetHint = process.env.TARGET_HINT || "fxg.jinritemai.com/ffa/g/create";

async function readTargets() {
  const response = await fetch(cdpListUrl);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text.slice(0, 1000) };
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 500)}`);
  }
  return Array.isArray(payload) ? payload : [];
}

async function inspectPageState(target) {
  if (!target?.webSocketDebuggerUrl) return null;
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  try {
    await client.call("Runtime.enable");
    const result = await client.call("Runtime.evaluate", {
      expression: `(() => {
        const text = document.body?.innerText || "";
        const attrFields = Array.from(document.querySelectorAll("[attr-field-id]"))
          .slice(0, 30)
          .map((el) => el.getAttribute("attr-field-id"))
          .filter(Boolean);
        return {
          href: location.href,
          title: document.title,
          readyState: document.readyState,
          hasLoginText: /登录|扫码|手机号|验证码/.test(text),
          hasPublishFields: /商品标题|主图上传|类目属性|图文信息|价格与库存|下一步/.test(text),
          attrFields,
          textSample: text.slice(0, 500)
        };
      })()`,
      returnByValue: true,
    });
    return result.result?.value || null;
  } finally {
    client.close();
  }
}

let result;
try {
  const targets = await readTargets();
  const pageTargets = targets.filter((item) => item.type === "page");
  const matchingTargets = pageTargets.filter(
    (item) => String(item.url || "").includes(targetHint) || String(item.title || "").includes(targetHint)
  );
  let pageState = null;
  let pageStateError = "";
  if (matchingTargets.length > 0) {
    try {
      pageState = await inspectPageState(matchingTargets[0]);
    } catch (error) {
      pageStateError = error instanceof Error ? error.message : String(error);
    }
  }
  const pageLooksReady = Boolean(pageState && !pageState.hasLoginText && pageState.hasPublishFields);
  result = {
    ok: true,
    cdpListUrl,
    targetHint,
    targetCount: targets.length,
    pageTargetCount: pageTargets.length,
    matchingTargetCount: matchingTargets.length,
    matchingTargets: matchingTargets.map((item) => ({
      id: item.id,
      title: item.title,
      url: item.url,
    })),
    pageState,
    pageStateError: pageStateError || undefined,
    readyForFxgProtocolProbe: matchingTargets.length > 0 && pageLooksReady,
    nextStep: matchingTargets.length && pageLooksReady
      ? "Run read-only FXG probes or targeted local preflight capture."
      : "Open the logged-in FXG publish page in a Chrome instance that was started with a remote debugging port.",
  };
} catch (error) {
  result = {
    ok: false,
    cdpListUrl,
    targetHint,
    readyForFxgProtocolProbe: false,
    error: error instanceof Error ? error.message : String(error),
    nextStep:
      "No Chrome DevTools endpoint is reachable. Do not claim live page evidence until Chrome is running with --remote-debugging-port and the logged-in FXG page is visible in /json/list.",
  };
}

const output = JSON.stringify(result, null, 2);
if (process.env.OUTPUT_PATH) {
  await fs.mkdir(path.dirname(process.env.OUTPUT_PATH), { recursive: true });
  await fs.writeFile(process.env.OUTPUT_PATH, output, "utf8");
}
console.log(output);
