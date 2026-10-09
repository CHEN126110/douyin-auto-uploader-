/**
 * 淘宝发布 —— 只读请求观察器。
 *
 * 用途：在用户**手动**操作发布工作台时，被动记录平台发出的读写请求，用于给
 * `contracts/field_mapping.json` 补证据（尤其是写接口的字段名）。
 *
 * 与抖店那边 `capture-fxg-submit-preflight.mjs` 的本质区别：
 *   抖店脚本会 `Fetch.enable` 拦截写请求；这里**只用 Network 域被动观察**，
 *   完全不介入请求生命周期——不拦截、不修改、不重放、不重发。
 *   换句话说：本脚本存在与否，都不会改变页面上发生的事。
 *
 * 硬约束：
 *   - 不点击、不输入、不提交、不导航。
 *   - 不保存 cookie / token / `_m_h5_tk` / 完整签名 URL / 未脱敏请求头。
 *     原始产物写进 taobao-publisher/tmp/（已 gitignore），
 *     必须 `python -m taobao_publish sanitize` 之后才能进 captures/。
 *
 * 用法（另开一个窗口，自己手动在浏览器里操作发布流程）：
 *   node taobao-publisher/scripts/capture-publish-requests.mjs
 *   node taobao-publisher/scripts/capture-publish-requests.mjs --seconds 300
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { CdpClient } from "../../mcp-server/cdp-client.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SUBPROJECT_ROOT = path.resolve(__dirname, "..");

const CDP_LIST_URL = process.env.TAOBAO_CDP_LIST_URL || "http://127.0.0.1:9334/json/list";
const ALLOWED_HOST_SUFFIXES = [".taobao.com", ".tmall.com"];
const TARGET_HINTS = ["item.upload.taobao.com", "item.upload.tmall.com"];

/** 只记录这些 host 的请求，避免把无关第三方流量写进产物。 */
const INTERESTING_HOSTS = [
  "item.upload.taobao.com",
  "item.upload.tmall.com",
  "h5api.m.taobao.com",
  "mtop.taobao.com",
  "api.m.taobao.com",
  "market.m.taobao.com",
  "img.taobao.com",
  "stream.taobao.com",
  "qn.taobao.com",
];

/**
 * 观察阶段**必然**会出现的写操作名称片段。命中即高亮提示，
 * 让人知道「刚刚那一下真的写进平台了」。
 */
const WRITE_HINTS = [
  "publish",
  "submit",
  "save",
  "add",
  "update",
  "create",
  "upload",
  "commit",
  "apply",
];

const MAX_BODY_CHARS = 4000;

function parseArgs(argv) {
  const options = { seconds: 180, out: "", wait: 120 };
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--seconds") options.seconds = Number(argv[++index]);
    else if (token === "--out") options.out = String(argv[++index] || "");
    else if (token === "--wait") options.wait = Number(argv[++index]);
  }
  if (!Number.isFinite(options.seconds) || options.seconds <= 0) options.seconds = 180;
  if (!Number.isFinite(options.wait) || options.wait < 0) options.wait = 120;
  return options;
}

/**
 * 等 CDP 与目标页出现。
 *
 * 为什么需要：早先的实现一上来就 `readTargets()`，Chrome 还在启动（或刚被关掉
 * 重启）时就立刻报「连不上」退出。观察器本该是「挂上去等」的东西，
 * 不该比它观察的对象还脆弱。
 */
async function waitForTarget(seconds) {
  const deadline = Date.now() + seconds * 1000;
  let lastMessage = "尚未尝试";
  while (Date.now() < deadline) {
    try {
      const targets = await readTargets();
      const target = pickTarget(targets);
      if (target) return target;
      lastMessage = "没有找到淘宝/天猫标签页";
    } catch (error) {
      lastMessage = error.message;
    }
    console.log(`[等待] ${lastMessage}（最多再等 ${Math.max(0, Math.round((deadline - Date.now()) / 1000))} 秒）`);
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
  throw new Error(`等待 ${seconds} 秒后仍未就绪：${lastMessage}`);
}

function isAllowedHost(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return ALLOWED_HOST_SUFFIXES.some((suffix) => host === suffix.slice(1) || host.endsWith(suffix));
  } catch {
    return false;
  }
}

function isInteresting(url) {
  try {
    const host = new URL(url).hostname.toLowerCase();
    return INTERESTING_HOSTS.some((item) => host === item || host.endsWith("." + item));
  } catch {
    return false;
  }
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

function truncate(value, limit = MAX_BODY_CHARS) {
  const text = String(value == null ? "" : value);
  return text.length > limit ? text.slice(0, limit) + `…<截断，原长 ${text.length}>` : text;
}

async function main() {
  const options = parseArgs(process.argv.slice(2));

  if (!CDP_LIST_URL.includes(":9334")) {
    throw new Error(
      `CDP 地址 ${CDP_LIST_URL} 不是淘宝端口 9334。抖店用 9333，两者登录态不可混用。`
    );
  }

  console.log("=".repeat(72));
  console.log("淘宝发布 · 只读请求观察");
  console.log("=".repeat(72));

  // 挂上去等，而不是连不上就死——Chrome 可能还没起来，或者用户正在扫码。
  const target = await waitForTarget(options.wait);

  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();

  /** requestId → 记录 */
  const records = new Map();
  const order = [];
  let writeLikeCount = 0;

  const record = (requestId) => {
    if (!records.has(requestId)) {
      records.set(requestId, {
        request_id: requestId,
        method: "",
        url: "",
        host: "",
        resource_type: "",
        post_data: "",
        post_data_truncated: false,
        request_headers: {},
        status: null,
        mime_type: "",
        response_ret: [],
        write_like: false,
        write_hint_hits: [],
      });
      order.push(requestId);
    }
    return records.get(requestId);
  };

  client.onEvent((method, params) => {
    if (method === "Network.requestWillBeSent") {
      const url = String(params.request?.url || "");
      if (!isInteresting(url)) return;
      const entry = record(params.requestId);
      entry.method = String(params.request?.method || "");
      entry.url = url;
      try {
        entry.host = new URL(url).hostname;
      } catch {
        entry.host = "";
      }
      entry.resource_type = String(params.type || "");
      entry.request_headers = { ...(params.request?.headers || {}) };
      const postData = params.request?.postData;
      if (postData) {
        entry.post_data = truncate(postData);
        entry.post_data_truncated = String(postData).length > MAX_BODY_CHARS;
      }
      const lower = (url + " " + entry.method).toLowerCase();
      entry.write_hint_hits = WRITE_HINTS.filter((hint) => lower.includes(hint));
      entry.write_like = entry.method !== "GET" && entry.write_hint_hits.length > 0;
      if (entry.write_like) writeLikeCount += 1;
      return;
    }

    if (method === "Network.responseReceived") {
      const entry = records.get(params.requestId);
      if (!entry) return;
      entry.status = params.response?.status ?? null;
      entry.mime_type = String(params.response?.mimeType || "");
      return;
    }
  });

  await client.call("Network.enable", { maxTotalBufferSize: 50 * 1024 * 1024 });

  console.log(`观察目标：${(() => { try { return new URL(target.url).hostname; } catch { return "?"; } })()}`);
  console.log(`观察时长：${options.seconds} 秒`);
  console.log("");
  console.log("现在请**手动**在浏览器里操作发布流程（选类目、填标题、传图、提交……）。");
  console.log("本脚本只观察请求，不拦截、不修改、不重放、不代替你做任何操作。");
  console.log("");

  await new Promise((resolve) => setTimeout(resolve, options.seconds * 1000));

  // 尽力回读 XHR/fetch 响应体，用于拿到 mtop 的 ret 与业务错误码。
  for (const requestId of order) {
    const entry = records.get(requestId);
    if (!entry || !["XHR", "Fetch"].includes(entry.resource_type)) continue;
    try {
      const body = await client.call("Network.getResponseBody", { requestId });
      const text = body?.base64Encoded
        ? Buffer.from(String(body.body || ""), "base64").toString("utf8")
        : String(body?.body || "");
      // 只提取 ret 字段，整段响应体不入库（可能含大量店铺数据）
      const match = text.match(/"ret"\s*:\s*(\[[^\]]*\]|"[^"]*")/);
      if (match) {
        try {
          const parsed = JSON.parse(match[1]);
          entry.response_ret = Array.isArray(parsed) ? parsed.map(String) : [String(parsed)];
        } catch {
          entry.response_ret = [match[1]];
        }
      }
    } catch {
      /* 响应体可能已被浏览器丢弃，属正常情况 */
    }
  }

  client.close();

  const collected = order.map((id) => records.get(id)).filter(Boolean);
  const interesting = collected.filter((entry) => entry.write_like || entry.host.includes("mtop") || entry.url.includes("mtop"));

  // 时间戳里不能留 `.`：Windows 上以点结尾的目录名会被系统改写成别的名字。
  const stamp = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 14);
  const outDir = path.join(SUBPROJECT_ROOT, "tmp");
  await fs.mkdir(outDir, { recursive: true });
  const outFile = options.out
    ? path.resolve(options.out)
    : path.join(outDir, `tb_publish_requests_raw_${stamp}.json`);

  await fs.writeFile(
    outFile,
    JSON.stringify(
      {
        probe_kind: "taobao_publish_request_observation_readonly",
        generated_at: new Date().toISOString(),
        cdp_list_url: CDP_LIST_URL,
        duration_seconds: options.seconds,
        note:
          "被动观察产物。未拦截、未修改、未重放任何请求。" +
          "含 cookie/token/签名的原始文本必须先脱敏才能进 captures/。",
        totals: {
          interesting_requests: collected.length,
          write_like_requests: writeLikeCount,
          mtop_requests: collected.filter((entry) => entry.url.includes("mtop")).length,
        },
        requests: collected,
      },
      null,
      2
    ),
    "utf8"
  );

  console.log("=".repeat(72));
  console.log(`共记录 ${collected.length} 条相关请求，其中疑似写操作 ${writeLikeCount} 条。`);
  console.log("");
  for (const entry of interesting.slice(0, 40)) {
    const flag = entry.write_like ? "[写?]" : "[读] ";
    const ret = entry.response_ret.length ? ` ret=${entry.response_ret[0]}` : "";
    console.log(`${flag} ${entry.method.padEnd(5)} ${entry.resource_type.padEnd(6)} ${entry.status ?? "-"} ${entry.host}${ret}`);
  }
  if (interesting.length > 40) console.log(`...另有 ${interesting.length - 40} 条`);
  console.log("");
  console.log("本次未执行：点击 / 输入 / 上传 / 保存草稿 / 提交 / 请求拦截 / 请求重放。");
  console.log(`原始产物：${path.relative(process.cwd(), outFile)}`);
  console.log("");
  console.log("下一步（脱敏后才可进仓库）：");
  console.log(
    `  python -m taobao_publish sanitize "${path.relative(process.cwd(), outFile)}" ` +
      `"taobao-publisher/captures/tb_publish_requests_${stamp}.json"`
  );
}

main().catch((error) => {
  console.error(`[观察器失败] ${error.message}`);
  process.exitCode = 1;
});
