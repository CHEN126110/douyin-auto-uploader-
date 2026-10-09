/**
 * Read-only readiness check for the Taobao publish research environment.
 * Reports whether a logged-in publish page is reachable over CDP.
 * Never clicks, uploads, saves or submits anything.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { CdpClient } from "../../mcp-server/cdp-client.js";

const cdpListUrl = process.env.TAOBAO_CDP_LIST_URL || "http://127.0.0.1:9334/json/list";
const targetHint = process.env.TARGET_HINT || "item.upload.taobao.com";

async function readTargets() {
  const response = await fetch(cdpListUrl);
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text.slice(0, 1000) };
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${JSON.stringify(payload).slice(0, 500)}`);
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
        return {
          href: location.href,
          title: document.title,
          readyState: document.readyState,
          onLoginPage: /login\.taobao\.com/.test(location.href),
          hasLoginText: /扫码登录|密码登录|请使用手机淘宝|账号登录/.test(text),
          hasPublishEntry: /以图发品|搜索发品|图片上传|发布商品|商品发布/.test(text),
          textSample: text.replace(/\s+/g, " ").slice(0, 600)
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
  const matching = pageTargets.filter(
    (item) => String(item.url || "").includes(targetHint) || String(item.title || "").includes(targetHint)
  );

  let pageState = null;
  let pageStateError = "";
  const probeTarget = matching[0] || pageTargets.find((i) => String(i.url || "").includes("taobao.com"));
  if (probeTarget) {
    try {
      pageState = await inspectPageState(probeTarget);
    } catch (error) {
      pageStateError = error instanceof Error ? error.message : String(error);
    }
  }

  const loggedIn = Boolean(pageState && !pageState.onLoginPage && !pageState.hasLoginText);
  result = {
    ok: true,
    cdpListUrl,
    targetHint,
    targetCount: targets.length,
    pageTargetCount: pageTargets.length,
    matchingTargetCount: matching.length,
    pageTargets: pageTargets.map((i) => ({ id: i.id, title: i.title, url: i.url })),
    pageState,
    pageStateError: pageStateError || undefined,
    readyForTaobaoProbe: Boolean(probeTarget) && loggedIn && Boolean(pageState?.hasPublishEntry),
    nextStep:
      loggedIn && pageState?.hasPublishEntry
        ? "Run read-only Taobao publish probes."
        : "Log in manually in the CDP Chrome window and open the publish page, then re-run this check.",
  };
} catch (error) {
  result = {
    ok: false,
    cdpListUrl,
    targetHint,
    readyForTaobaoProbe: false,
    error: error instanceof Error ? error.message : String(error),
    nextStep:
      "No Chrome DevTools endpoint reachable on this port. Start the research Chrome first; do not claim live evidence without it.",
  };
}

const output = JSON.stringify(result, null, 2);
if (process.env.OUTPUT_PATH) {
  await fs.mkdir(path.dirname(process.env.OUTPUT_PATH), { recursive: true });
  await fs.writeFile(process.env.OUTPUT_PATH, output, "utf8");
}
console.log(output);
