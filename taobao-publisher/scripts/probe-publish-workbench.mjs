/**
 * 淘宝发布工作台 —— 只读结构勘察探针。
 *
 * 用途：为 `contracts/selectors.json` 与 `contracts/field_mapping.json` 收集**证据**。
 * 它只能看，不能动。作为对比，抖店那边的 probe 脚本允许在 `UPLOAD_*` 授权下触发上传，
 * 这里**连那个开关都没有**——因为淘宝发布页的字段一条都没实证，任何写操作都无从设计。
 *
 * 硬约束（与 taobao-publisher/AGENTS.md 一致）：
 *   - 不点击、不输入、不提交、不导航、不上传。
 *   - 不读取任何输入框的 value（页面可能已被卖家填过资料）。
 *   - 原始产物写进 taobao-publisher/tmp/（已 gitignore），
 *     要用 `python -m taobao_publish sanitize` 脱敏后才能进 captures/。
 *
 * 用法：
 *   node taobao-publisher/scripts/probe-publish-workbench.mjs
 *   TAOBAO_CDP_LIST_URL=http://127.0.0.1:9334/json/list node taobao-publisher/scripts/probe-publish-workbench.mjs
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CdpClient } from "../../mcp-server/cdp-client.js";
import { DETAIL_EXPRESSION } from "./lib/workbench-snapshot.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SUBPROJECT_ROOT = path.resolve(__dirname, "..");

const CDP_LIST_URL = process.env.TAOBAO_CDP_LIST_URL || "http://127.0.0.1:9334/json/list";
const ALLOWED_HOST_SUFFIXES = [".taobao.com", ".tmall.com"];
const TARGET_HINTS = ["item.upload.taobao.com", "item.upload.tmall.com"];

/** 只允许在淘宝/天猫域名上运行。 */
function isAllowedHost(url) {
  let host;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  return ALLOWED_HOST_SUFFIXES.some(
    (suffix) => host === suffix.slice(1) || host.endsWith(suffix)
  );
}

async function readTargets() {
  let response;
  try {
    response = await fetch(CDP_LIST_URL);
  } catch (error) {
    throw new Error(
      `连不上 ${CDP_LIST_URL}（${error.message}）。\n` +
        "淘宝调试实例可能没启动。先运行：\n" +
        "  node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs\n" +
        "该 profile 需要独立扫码登录一次（复制 cookie 库已实证失败，别再试）。"
    );
  }
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${CDP_LIST_URL}`);
  const payload = await response.json();
  if (!Array.isArray(payload)) throw new Error(`${CDP_LIST_URL} 返回的不是数组`);
  return payload;
}

function pickTarget(targets) {
  const pages = targets.filter((item) => item.type === "page" && item.webSocketDebuggerUrl);
  for (const hint of TARGET_HINTS) {
    const hit = pages.find((item) => String(item.url || "").includes(hint));
    if (hit) return hit;
  }
  return pages.find((item) => isAllowedHost(item.url)) || null;
}

/**
 * 页面内执行的勘察脚本。
 *
 * 关键设计：**只读属性、绝不触碰 value**。返回的是「页面上有什么控件」这类
 * 结构事实，供人推导候选选择器；不是「这些控件里填了什么」。
 */
// 页面内勘察表达式从共享模块导入，避免与 watch-publish-flow.mjs 各维护一份。
// 只读保证（不点击/不输入/不读 value）见 scripts/lib/workbench-snapshot.mjs 的模块注释。

function summarize(probe) {
  const lines = [];
  lines.push(`URL            : ${probe.href}`);
  lines.push(`标题           : ${probe.title}`);
  lines.push(`readyState     : ${probe.readyState}`);
  lines.push(`登录页         : ${probe.isLoginPage ? "是" : "否"}`);
  lines.push(`疑似发布工作台 : ${probe.hasWorkbenchKeyword ? "是" : "否"}`);
  lines.push(`控件数量       : ${JSON.stringify(probe.counts)}`);
  for (const [key, hits] of Object.entries(probe.keywordAreas || {})) {
    lines.push(`  ${key.padEnd(12)} 命中 ${hits.length} 个候选区块`);
  }
  return lines.join("\n");
}

async function main() {
  // 允许两种淘宝调试端口：
  //   9334      —— 本子项目的**研究会话**（独立 profile，抖店 9333 不可混用）
  //   9500-9599 —— **应用管理的桌面账户**端口段（见 docs/06-阻塞项.md B-16）
  //
  // 两种都必须是淘宝自己的 profile。真正防串店的是「标签页必须是 taobao.com/tmall.com」
  // （下面 pickTarget 的 TARGET_HINTS），端口只是第二道提示。
  const port = Number((CDP_LIST_URL.match(/:(\d+)\//) || [])[1] || 0);
  const isResearchPort = port === 9334;
  const isDesktopAccountPort = port >= 9500 && port <= 9599;
  if (!isResearchPort && !isDesktopAccountPort) {
    throw new Error(
      `CDP 地址 ${CDP_LIST_URL} 的端口 ${port} 不是淘宝端口。` +
        `研究用 9334，应用管理的桌面账户用 9500-9599；抖店用 9333，两者登录态不可混用。`
    );
  }

  const targets = await readTargets();
  const target = pickTarget(targets);
  if (!target) {
    throw new Error(
      "没有找到淘宝/天猫标签页。请先运行：\n" +
        "  node protocol-research-taobao-20260908/scripts/start-taobao-cdp-chrome.mjs\n" +
        "并在该窗口扫码登录、打开 https://item.upload.taobao.com/sell/ai/category.htm"
    );
  }

  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  let probe;
  try {
    await client.call("Runtime.enable");
    const result = await client.call("Runtime.evaluate", {
      expression: DETAIL_EXPRESSION,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`页面内勘察脚本抛错：${result.exceptionDetails.text || "unknown"}`);
    }
    probe = result.result?.value || null;
  } finally {
    client.close();
  }

  if (!probe) throw new Error("页面内勘察未返回数据");

  // 时间戳里不能留 `.`：Windows 上以点结尾的目录名会被系统改写成别的名字。
  const stamp = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
  const outDir = path.join(SUBPROJECT_ROOT, "tmp");
  await fs.mkdir(outDir, { recursive: true });
  const outFile = path.join(outDir, `tb_workbench_probe_raw_${stamp}.json`);
  await fs.writeFile(
    outFile,
    JSON.stringify(
      {
        probe_kind: "taobao_publish_workbench_readonly",
        generated_at: new Date().toISOString(),
        cdp_list_url: CDP_LIST_URL,
        // 只记 host，不记完整 URL（URL 上可能挂 token 参数）
        target_host: (() => {
          try { return new URL(target.url).hostname; } catch { return ""; }
        })(),
        note: "只读勘察：未点击、未输入、未提交、未导航。原始产物需脱敏后才能进 captures/。",
        probe,
      },
      null,
      2
    ),
    "utf8"
  );

  console.log("=".repeat(72));
  console.log("淘宝发布工作台 · 只读勘察");
  console.log("=".repeat(72));
  console.log(summarize(probe));
  console.log("");
  console.log("本次未执行：点击 / 输入 / 上传 / 保存草稿 / 提交 / 页面导航。");
  console.log(`原始产物：${path.relative(process.cwd(), outFile)}`);
  console.log("");
  console.log("下一步（脱敏后才可进仓库）：");
  console.log(
    `  python -m taobao_publish sanitize "${path.relative(process.cwd(), outFile)}" ` +
      `"taobao-publisher/captures/tb_workbench_probe_${stamp}.json"`
  );
}

main().catch((error) => {
  console.error(`[探针失败] ${error.message}`);
  process.exitCode = 1;
});
