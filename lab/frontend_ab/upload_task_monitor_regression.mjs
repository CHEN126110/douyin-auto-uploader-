import assert from "node:assert/strict";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import esbuild from "../../tauri-app/node_modules/esbuild/lib/main.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "../..");
const src = path.join(repo, "tauri-app/src");
const entry = path.resolve(process.argv[2] || path.join(src, "composables/useUploadTaskMonitor.ts"));
const work = path.join(here, ".work", "upload-monitor-regression");
fs.mkdirSync(work, { recursive: true });

const mocks = {
  "element-plus": `
    export const ElButton = { name: "ElButton" };
    export const ElMessage = new Proxy({}, { get: () => () => undefined });
    export const ElMessageBox = { alert: (...args) => globalThis.__monitorMocks.alert(...args) };
    export const ElLoading = { service: (...args) => globalThis.__monitorMocks.loading(...args) };
  `,
  api: `
    export const api = new Proxy({}, { get: (_target, key) =>
      (...args) => globalThis.__monitorMocks.api(String(key), ...args) });
    export const apiErrorMessage = (error) => String(error && error.message || error);
  `,
  store: `export const useProductStore = () => globalThis.__monitorMocks.store;`,
};

await esbuild.build({
  entryPoints: [entry],
  outfile: path.join(work, "useUploadTaskMonitor.mjs"),
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node20",
  sourcemap: false,
  tsconfig: path.join(repo, "tauri-app/tsconfig.json"),
  plugins: [{
    name: "upload-monitor-test-doubles",
    setup(build) {
      build.onResolve({ filter: /^element-plus$/ }, () => ({ path: "element-plus", namespace: "monitor-mock" }));
      build.onResolve({ filter: /^@\/services\/api$/ }, () => ({ path: "api", namespace: "monitor-mock" }));
      build.onResolve({ filter: /^@\/stores\/productStore$/ }, () => ({ path: "store", namespace: "monitor-mock" }));
      build.onResolve({ filter: /^@\// }, args => {
        const target = path.join(src, args.path.slice(2));
        if (path.extname(target)) return { path: target };
        if (fs.existsSync(`${target}.ts`)) return { path: `${target}.ts` };
        return { path: path.join(target, "index.ts") };
      });
      build.onLoad({ filter: /.*/, namespace: "monitor-mock" }, args => ({
        contents: mocks[args.path], loader: "js", resolveDir: work,
      }));
    },
  }],
});

const tasks = {
  A: {
    task_id: "A", platform: "taobao", account_profile: "account-A", record_id: 1,
    status: "failed", progress: 100, message: "任务 A 失败", error: "任务 A 失败",
    dry_run: false, stop_before_submit: true, publish_confirmed: false, steps: [],
  },
  B: {
    task_id: "B", platform: "taobao", account_profile: "account-A", record_id: 1,
    status: "succeeded", progress: 100, message: "任务 B 完成",
    dry_run: false, stop_before_submit: false, publish_confirmed: false, steps: [],
    result: { success: true, stopped_before_submit: false },
  },
  C: {
    task_id: "C", platform: "taobao", account_profile: "account-A", record_id: 1,
    status: "running", progress: 45, message: "任务 C 进行中",
    dry_run: false, stop_before_submit: true, publish_confirmed: false, steps: [],
  },
};

const apiCalls = [];
const alertCalls = [];
const loadingCalls = [];
let resolveOldAlert;
let resolveC;
let nextTimer = 1;
const timers = new Map();
const oldAlert = new Promise(resolve => { resolveOldAlert = resolve; });

globalThis.__monitorMocks = {
  async alert(message, title, options) {
    alertCalls.push({ message, title, options });
    if (message === "任务 A 失败") return oldAlert;
    return "ok";
  },
  loading(options) {
    const instance = { options, closed: false, close() { this.closed = true; } };
    loadingCalls.push(instance);
    return instance;
  },
  async api(method, ...args) {
    apiCalls.push({ method, args });
    if (method === "getTaobaoPublishStatus") {
      const taskId = args[0];
      if (taskId === "C") {
        const response = await new Promise(resolve => { resolveC = resolve; });
        return response;
      }
      return { success: true, data: tasks[taskId] };
    }
    throw new Error(`未预期的 API：${method}`);
  },
  store: {
    currentProductId: 1,
    async fetchProducts() {},
    async refreshCurrentProductSilently() {},
  },
};

globalThis.window = {
  setInterval(callback) {
    const id = nextTimer++;
    timers.set(id, callback);
    return id;
  },
  clearInterval(id) { timers.delete(id); },
};

const flush = async (rounds = 12) => {
  for (let index = 0; index < rounds; index += 1) {
    await new Promise(resolve => setImmediate(resolve));
  }
};

const { pathToFileURL } = await import("node:url");
const { useUploadTaskMonitor } = await import(`${pathToFileURL(path.join(work, "useUploadTaskMonitor.mjs")).href}?t=${Date.now()}`);
const monitor = useUploadTaskMonitor();

try {
  // A 的终态弹窗始终不确认：旧实现会让 uploadPollInFlight 一直为 true。
  monitor.startUploadMonitoring("A", "external", null, "taobao", { recordId: 1, accountProfile: "account-A" });
  await flush();
  assert.equal(alertCalls.length, 1, "A 应先停在结果确认弹窗");
  assert.equal(alertCalls[0].message, "任务 A 失败");

  // A 的弹窗尚未确认时接入 B：B 必须独立读到终态，不能永远停在“正在读取上传进度…”。
  monitor.startUploadMonitoring("B", "external", null, "taobao", { recordId: 1, accountProfile: "account-A" });
  await flush();
  const bPolls = apiCalls.filter(call => call.method === "getTaobaoPublishStatus" && call.args[0] === "B");
  const bFinished = alertCalls.some(call => call.message === "流水线已完成并执行了提交。是否已上架请在卖家中心核对");

  // 同一个任务已经有请求在途时，重试进度不能再发第二个相同请求。
  monitor.startUploadMonitoring("C", "external", null, "taobao", { recordId: 1, accountProfile: "account-A" });
  await flush();
  await monitor.retryUploadProgress();
  await flush();
  const cPolls = apiCalls.filter(call => call.method === "getTaobaoPublishStatus" && call.args[0] === "C");
  if (resolveC) resolveC({ success: true, data: tasks.C });
  await flush();

  const evidence = {
    entry,
    aAlertStillUnconfirmed: true,
    bPolls: bPolls.length,
    bFinished,
    cPollsWhileFirstRequestInFlight: cPolls.length,
    activeTaskAfterChecks: monitor.activeUploadTaskId.value,
  };
  if (!bPolls.length || !bFinished || cPolls.length !== 1) {
    console.error(JSON.stringify({ ...evidence, alertCalls, apiCalls }, null, 2));
  }
  assert.ok(bPolls.length > 0, "旧结果弹窗未确认时，新任务 B 没有发起任何进度请求");
  assert.ok(bFinished, "新任务 B 没有进入完成处理");
  assert.equal(cPolls.length, 1, "同一任务的在途请求未完成时不允许重复轮询");
  console.log(JSON.stringify({ ok: true, ...evidence }, null, 2));
} finally {
  resolveOldAlert("closed");
  if (resolveC) resolveC({ success: true, data: tasks.C });
  monitor.stopUploadMonitoring();
  await flush();
}
