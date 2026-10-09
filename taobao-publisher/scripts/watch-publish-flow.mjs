/**
 * 淘宝发布流程 —— 自动分步观察器（只读）。
 *
 * ## 为什么需要它
 *
 * `probe-publish-workbench.mjs` 是**一次性**快照：你每走一步就得手动重跑一次。
 * 淘宝发布流程有 6–7 步，手动重跑极易漏步，而我们只有一次登录会话可浪费。
 *
 * 本脚本每 `--interval` 毫秒问一次页面「你换步了吗」（用轻量指纹判断），
 * 一换步就落一份完整结构快照。你只需要在浏览器里正常走一遍流程，
 * 不用管脚本、不用回来找我。
 *
 * ## 只读保证
 *
 * - 只做 `Runtime.evaluate` 读属性，**不点击、不输入、不提交、不导航、不上传**。
 * - 不读取输入框的 `value`。
 * - 轮询是「读页面」而非「打平台」：不发任何网络请求到淘宝，只连本机 9334。
 *   因此不构成高频探测。
 *
 * ## 用法
 *
 * ```powershell
 * node taobao-publisher/scripts/watch-publish-flow.mjs
 * node taobao-publisher/scripts/watch-publish-flow.mjs --seconds 1800 --interval 2000
 * ```
 *
 * 产出：`taobao-publisher/tmp/publish-flow-<时间戳>/step-NN.json`（原始产物，
 * 已 gitignore）。要进仓库必须先过 `python -m taobao_publish sanitize`。
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CdpClient } from "../../mcp-server/cdp-client.js";
import { DETAIL_EXPRESSION, FINGERPRINT_EXPRESSION, fingerprintKey } from "./lib/workbench-snapshot.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SUBPROJECT_ROOT = path.resolve(__dirname, "..");

const CDP_LIST_URL = process.env.TAOBAO_CDP_LIST_URL || "http://127.0.0.1:9334/json/list";
const ALLOWED_HOST_SUFFIXES = [".taobao.com", ".tmall.com"];
const TARGET_HINTS = ["item.upload.taobao.com", "item.upload.tmall.com"];

/** 最多落多少份，避免脚本被遗忘在后台时把磁盘写满。 */
const MAX_STEPS = 40;

function parseArgs(argv) {
  const options = { seconds: 900, interval: 1500, out: "" };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--seconds") options.seconds = Number(argv[++index]);
    else if (token === "--interval") options.interval = Number(argv[++index]);
    else if (token === "--out") options.out = String(argv[++index] || "");
  }
  if (!Number.isFinite(options.seconds) || options.seconds <= 0) options.seconds = 900;
  if (!Number.isFinite(options.interval) || options.interval < 500) options.interval = 1500;
  return options;
}

function isAllowedHost(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return ALLOWED_HOST_SUFFIXES.some((suffix) => host === suffix.slice(1) || host.endsWith(suffix));
  } catch {
    return false;
  }
}

async function readTargets() {
  const response = await fetch(CDP_LIST_URL);
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${CDP_LIST_URL}`);
  const payload = await response.json();
  if (!Array.isArray(payload)) throw new Error(`${CDP_LIST_URL} 返回的不是数组`);
  return payload;
}

/**
 * 挑选当前该观察的页面。
 *
 * 优先级：发布工作台 → 登录页（要提示用户扫码）→ 任意淘宝/天猫页。
 * 登录页也要能选上，否则用户扫码前脚本只会干等，看不到任何提示。
 */
function pickTarget(targets) {
  const pages = targets.filter((item) => item.type === "page" && item.webSocketDebuggerUrl);
  for (const hint of TARGET_HINTS) {
    const hit = pages.find((item) => String(item.url || "").includes(hint));
    if (hit) return hit;
  }
  const login = pages.find((item) => String(item.url || "").includes("login.taobao.com"));
  if (login) return login;
  return pages.find((item) => isAllowedHost(item.url)) || null;
}

function shortUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname + parsed.pathname;
  } catch {
    return String(url || "").slice(0, 80);
  }
}

function stamp() {
  // 时间戳里不能留 `.`：Windows 上以点结尾的目录名会被系统改写成别的名字。
  return new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
}

async function evaluate(client, expression) {
  await client.call("Runtime.enable");
  const result = await client.call("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "页面内表达式抛错");
  }
  return result.result?.value ?? null;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));

  if (!CDP_LIST_URL.includes(":9334")) {
    throw new Error(
      `CDP 地址 ${CDP_LIST_URL} 不是淘宝端口 9334。抖店用 9333，两者登录态不可混用。`
    );
  }

  const outDir = options.out
    ? path.resolve(options.out)
    : path.join(SUBPROJECT_ROOT, "tmp", `publish-flow-${stamp()}`);
  await fs.mkdir(outDir, { recursive: true });

  console.log("=".repeat(72));
  console.log("淘宝发布流程 · 自动分步观察（只读）");
  console.log("=".repeat(72));
  console.log(`观察时长：${options.seconds} 秒    轮询间隔：${options.interval} ms`);
  console.log(`产出目录：${path.relative(process.cwd(), outDir)}`);
  console.log("");
  console.log("请在浏览器里**正常手动走一遍**发布流程（选类目 → 填标题 → 属性 →");
  console.log("规格 → 主图 → 价格库存 → 运费）。本脚本只记录页面结构，");
  console.log("不点击、不输入、不提交。走到「保存草稿」前停下即可。");
  console.log("");
  console.log("---- 实时日志 ----");

  const deadline = Date.now() + options.seconds * 1000;
  let currentTargetId = "";
  let client = null;
  let lastKey = "";
  let stepCount = 0;
  let announcedLogin = false;

  const closeClient = () => {
    try {
      client?.close();
    } catch {
      /* 关闭失败无所谓 */
    }
    client = null;
    currentTargetId = "";
  };

  try {
    while (Date.now() < deadline && stepCount < MAX_STEPS) {
      let targets;
      try {
        targets = await readTargets();
      } catch (error) {
        console.log(`[等待] 连不上 ${CDP_LIST_URL}（${error.message}）`);
        closeClient();
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }

      const target = pickTarget(targets);
      if (!target) {
        console.log("[等待] 没有淘宝/天猫标签页");
        closeClient();
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }

      // 目标换了（新开标签页 / 关了旧页）就重连，否则复用同一条连接。
      if (target.id !== currentTargetId) {
        closeClient();
        client = new CdpClient(target.webSocketDebuggerUrl);
        await client.connect();
        currentTargetId = target.id;
        console.log(`[连接] ${shortUrl(target.url)}`);
      }

      let fingerprint;
      try {
        fingerprint = await evaluate(client, FINGERPRINT_EXPRESSION);
      } catch (error) {
        console.log(`[重连] ${error.message}`);
        closeClient();
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }

      const onLoginPage = /login\.taobao\.com|login\.tmall\.com/.test(String(fingerprint?.href || ""));
      if (onLoginPage) {
        if (!announcedLogin) {
          console.log("[需要登录] 当前在淘宝登录页 —— 请在 Chrome 窗口里扫码登录，脚本会自己继续。");
          announcedLogin = true;
        }
        // 刻意**不**断开连接：留在登录页时反复重连没有意义，只会刷屏。
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }
      announcedLogin = false;

      const key = fingerprintKey(fingerprint);
      if (key === lastKey) {
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }
      lastKey = key;
      stepCount += 1;

      let detail = null;
      try {
        detail = await evaluate(client, DETAIL_EXPRESSION);
      } catch (error) {
        console.log(`[跳过] 详情快照失败：${error.message}`);
        await new Promise((resolve) => setTimeout(resolve, options.interval));
        continue;
      }

      const fileName = `step-${String(stepCount).padStart(2, "0")}.json`;
      const filePath = path.join(outDir, fileName);
      await fs.writeFile(
        filePath,
        JSON.stringify(
          {
            probe_kind: "taobao_publish_flow_step_readonly",
            step_index: stepCount,
            captured_at: new Date().toISOString(),
            note:
              "只读结构快照：未点击、未输入、未提交、未导航。" +
              "原始产物含页面文本，进仓库前必须过 python -m taobao_publish sanitize。",
            fingerprint,
            detail,
          },
          null,
          2
        ),
        "utf8"
      );

      const counts = detail?.counts || {};
      console.log(
        `[步骤 ${String(stepCount).padStart(2, "0")}] ${shortUrl(fingerprint.href)}` +
          `  input=${counts.input ?? "?"} select=${counts.select ?? "?"}` +
          ` button=${counts.button ?? "?"} attr-field-id=${counts["[attr-field-id]"] ?? "?"}` +
          ` → ${fileName}`
      );

      await new Promise((resolve) => setTimeout(resolve, options.interval));
    }
  } finally {
    closeClient();
  }

  if (stepCount === 0) {
    console.log("");
    console.log("没有捕捉到任何步骤。可能原因：全程停在登录页，或页面完全没变化。");
  } else {
    console.log("");
    console.log(`共捕捉 ${stepCount} 个步骤快照。`);
  }
  console.log("");
  console.log("本次未执行：点击 / 输入 / 上传 / 保存草稿 / 提交 / 页面导航 / 请求拦截。");
  console.log("");
  console.log("下一步：");
  console.log("  1) 看每份 step-NN.json，确认页面结构与关键词分区；");
  console.log("  2) 用请求观察器的产物补写接口字段名；");
  console.log("  3) 脱敏后才允许进 captures/：");
  console.log(
    `     python -m taobao_publish sanitize "${path.relative(process.cwd(), outDir)}\\step-01.json" ` +
      `"taobao-publisher/captures/tb_flow_step01_${stamp()}.json"`
  );
}

main().catch((error) => {
  console.error(`[观察器失败] ${error.message}`);
  process.exitCode = 1;
});
