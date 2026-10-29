// 采集入口场景：链接校验 / 启动 / 进度 / 完成导入 / 失败重试 / 取消。
// 采集接口全部由代理给假响应（不会启动浏览器、不会访问淘宝）；验证主页对 CaptureSection 的 @imported 接线。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.capture_entry = async function (phase) {
    const H = window.__H;
    const ev = [];
    const note = (s) => ev.push(s);
    H.quiet();

    if (!window.__toastObserver) {
      window.__toastLog = [];
      window.__toastObserver = new MutationObserver((muts) => {
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType !== 1) continue;
            const els = n.matches && n.matches(".el-message") ? [n] : [...(n.querySelectorAll ? n.querySelectorAll(".el-message") : [])];
            els.forEach((e) => window.__toastLog.push(H.text(e)));
          }
        }
      });
      window.__toastObserver.observe(document.body, { childList: true, subtree: true });
    }
    const flushToasts = (label) => note(`[toast] ${label}: ${JSON.stringify(window.__toastLog.splice(0))}`);
    const ROOTS = [".product-manager", ".el-message-box"];
    const dump = async (name) => note(await H.dumpAll(`${phase}_capture_${name}.txt`, ROOTS));
    const btn = (text) => H.byText("button", text, H.q(".capture-section"));
    const urlInput = () => H.q(".capture-input input");
    const status = () => H.q(".capture-status");
    const IGNORE = new Set(["/api/upload/tasks", "/api/taobao/publish/tasks", "/api/shop/current", "/health", "/load_detail", "/settings", "/api/capture/history"]);
    const logSince = async (label) => {
      const log = (await H.ctl("log")).log.filter((e) => !IGNORE.has(e.path));
      note(`[requests ${label}] ${log.map((e) => `${e.method} ${e.path}`).join(" , ")}`);
      await H.save(`${phase}_capture_${label}_requests.jsonl`, log.map((e) => JSON.stringify({ body: e.body, method: e.method, mock: e.mock, path: e.path, query: e.query })).join("\n"));
    };
    const boxOpen = () => H.qa(".el-message-box").some(H.visible);

    await H.waitFor(() => H.q(".capture-section") && H.qa(".product-item").length > 0, { label: "主页加载完成" });
    await H.sleep(1500);
    note(`[capture panel] ${H.text(H.q(".capture-container")).slice(0, 120)}`);
    await dump("init");

    // 1. 空输入 / 不支持的链接
    await H.ctl("reset");
    await H.click(btn("开始采集"), "开始采集(空)");
    await H.sleep(300);
    flushToasts("空链接");
    H.setValue(urlInput(), "https://example.com/item/1");
    await H.sleep(200);
    await H.click(btn("开始采集"), "开始采集(不支持)");
    await H.sleep(300);
    flushToasts("不支持的链接");
    H.setValue(urlInput(), "http://[bad");
    await H.sleep(200);
    await H.click(btn("开始采集"), "开始采集(格式无效)");
    await H.sleep(300);
    flushToasts("无效格式");
    await logSince("invalid");

    // 2. 成功：启动 → 进度 → 完成导入 → 刷新商品列表
    await H.ctl("mock", { capture_mode: "success", reset_tasks: true });
    await H.ctl("reset");
    H.setValue(urlInput(), "item.taobao.com/item.htm?id=123456");
    await H.sleep(200);
    await H.click(btn("开始采集"), "开始采集");
    await H.waitFor(() => status(), { label: "出现采集状态" });
    await H.sleep(500);
    note(`[status started] ${H.text(status())} | btn=${H.qa(".capture-input-group button").map((b) => H.text(b)).join("/")} | input.disabled=${urlInput().disabled}`);
    await dump("started");
    await H.waitFor(() => /导入成功/.test(H.text(status() || document.body)), { label: "导入成功", timeout: 15000 });
    await H.sleep(500);
    note(`[status done] ${H.text(status())}`);
    flushToasts("采集成功");
    await dump("done");
    await H.waitFor(() => !status(), { label: "状态复位", timeout: 8000 });
    await H.sleep(400);
    note(`[after reset] input="${urlInput().value}"`);
    await logSince("success");

    // 3. 失败：可重试 → 重置
    await H.ctl("mock", { capture_mode: "failed", reset_tasks: true });
    await H.ctl("reset");
    H.setValue(urlInput(), "https://detail.1688.com/offer/123.html");
    await H.sleep(200);
    await H.click(btn("开始采集"), "开始采集(失败)");
    await H.waitFor(() => H.text(H.q(".capture-input-group") || document.body).includes("重试"), { label: "失败后出现重试", timeout: 15000 });
    await H.sleep(400);
    flushToasts("采集失败");
    note(`[status failed] ${H.text(status())} | btns=${H.qa(".capture-input-group button").map((b) => H.text(b)).join("/")}`);
    await dump("failed");
    await H.click(btn("重置"), "重置");
    await H.sleep(300);
    note(`[after failed reset] status=${!!status()} btns=${H.qa(".capture-input-group button").map((b) => H.text(b)).join("/")}`);
    await logSince("failed");

    // 4. 取消
    await H.ctl("mock", { capture_mode: "stuck", reset_tasks: true });
    await H.ctl("reset");
    H.setValue(urlInput(), "https://detail.tmall.com/item.htm?id=9");
    await H.sleep(200);
    await H.click(btn("开始采集"), "开始采集(卡住)");
    await H.waitFor(() => status() && /采集中/.test(H.text(status())), { label: "卡住的采集进度", timeout: 15000 });
    await H.sleep(300);
    await H.click(btn("取消"), "取消");
    const box = await H.waitFor(() => H.qa(".el-message-box").find((b) => H.visible(b)), { label: "取消确认框" });
    note(`[messagebox] ${H.text(box)}`);
    await H.click(H.q(".el-message-box__btns .el-button--primary", box), "确定取消");
    await H.waitFor(() => !boxOpen(), { label: "确认框关闭" });
    await H.sleep(500);
    flushToasts("取消采集");
    note(`[after cancel] status=${!!status()} input="${urlInput().value}"`);
    await dump("cancelled");
    await logSince("cancel");
    await H.ctl("mock", { capture_mode: null });

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_capture_events.txt`, ev.join("\n"));
    return `events=${ev.length} saved=${JSON.stringify(info)} dpr=${devicePixelRatio}`;
  };
})();
