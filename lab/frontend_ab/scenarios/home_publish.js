// 主页发布流程场景：抖音 / 淘宝 / 小红书 / 批量 / 外部任务接入。
// 所有「会操作平台」的接口都由代理给假响应（任务进度、结果、失败、500 等都是脚本化的）；
// 商品保存在发布前走假响应（mock_publish_save），不会碰真实平台，也不会启动浏览器。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.home_publish = async function (phase, only) {
    const H = window.__H;
    const ev = [];
    const note = (s) => ev.push(s);
    let restoreVisible = H.quiet();

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
    const ROOTS = [".product-manager", ".el-loading-mask", ".el-message-box"];
    const dump = async (flow, name) => note(await H.dumpAll(`${phase}_pubflow_${flow}_${name}.txt`, ROOTS));
    const btn = (root, text) => H.byText("button", text, root || document);
    const boxes = () => H.qa(".el-message-box").filter(H.visible);
    const boxOpen = () => boxes().length > 0;
    const answerBox = async (expect, accept = true) => {
      const box = await H.waitFor(() => boxes().find((b) => H.text(b).includes(expect)), { label: `对话框:${expect}`, timeout: 20000 });
      note(`[messagebox] ${H.text(box)}`);
      const buttons = H.qa(".el-message-box__btns .el-button", box);
      const target = accept ? buttons.find((b) => b.classList.contains("el-button--primary")) : buttons.find((b) => !b.classList.contains("el-button--primary"));
      await H.click(target, accept ? "确认" : "取消");
      // 只等「这一个」对话框关掉：连续的对话框（批量确认 → 发布确认 → 结果）会接着弹出下一个
      await H.waitFor(() => !box.isConnected || !H.visible(box), { label: "对话框关闭" });
      await H.sleep(300);
    };
    const overlay = () => H.q(".el-loading-mask.is-fullscreen");
    const detailIdle = () => !H.q(".right-panel .el-loading-mask");
    const items = () => H.qa(".product-item");
    const input = (ph) => H.q(`.product-form input[placeholder="${ph}"]`);
    const skuRows = () => H.qa(".sku-item");
    const actionButtons = () => H.qa(".action-buttons button");
    const publishBtn = () => actionButtons()[0];
    const batchBtn = () => actionButtons()[1];
    const mock = (patch) => H.ctl("mock", { reset_tasks: true, ...patch });
    const setSubmitMode = async (mode) => {
      const cur = await (await fetch("http://127.0.0.1:5002/settings")).json();
      const cfg = cur.data.settings.automation_config;
      cfg.publish_submit_mode = mode;
      const r = await (await fetch("http://127.0.0.1:5002/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ automation_config: cfg }) })).json();
      if (!r.success) throw new Error("设置提交方式失败");
    };
    const syncAccount = async (platform) => {
      await H.ctl("mock", { mock_platform: platform });
      const bar = document.querySelector(".shop-bar");
      await bar.__vueParentComponent.exposed.refresh(true, true);
      await H.sleep(400);
    };
    const IGNORE = new Set(["/api/upload/tasks", "/api/taobao/publish/tasks", "/api/products", "/api/shop/current", "/api/capture/history", "/health", "/load_detail"]);
    const resetLog = () => H.ctl("reset");
    const saveFlowLog = async (flow) => {
      const log = (await H.ctl("log")).log.filter((e) => !IGNORE.has(e.path));
      // 与 cmp.py 的 *_requests.jsonl 约定一致：每行一个 JSON（不含 status）
      await H.save(`${phase}_pubflow_${flow}_requests.jsonl`, log.map((e) => JSON.stringify({ body: e.body, method: e.method, mock: e.mock, path: e.path, query: e.query })).join("\n"));
      note(`[requests ${flow}] ${log.map((e) => `${e.method} ${e.path}`).join(" , ")}`);
    };
    // 保证当前商品信息完整（标题 / 库存 / SKU 价格），发布前校验才会通过
    const prepare = async (productIndex = 1) => {
      if (!/发布 · /.test(H.text(H.q(".form-title"))) || H.q(".right-panel .el-loading-mask")) await H.waitFor(detailIdle, { label: "详情加载" });
      const current = H.text(H.q(".form-title"));
      if (!current.includes(["", "测试船袜", "测试中筒袜"][productIndex] || "")) {
        await H.click(items()[productIndex], `商品 ${productIndex}`);
        await H.sleep(300);
        await H.waitFor(detailIdle, { label: "详情加载" });
        await H.sleep(500);
      }
      H.setValue(input("标题"), "测试袜子标题");
      H.setValue(input("设置库存"), "88");
      H.setValue(input("单价"), "10");
      await H.sleep(200);
      await H.click(btn(H.q(".price-row"), "填充"), "填充");
      await H.sleep(300);
      window.__toastLog.splice(0);
    };
    const waitIdle = async (label = "发布流程结束") => {
      await H.waitFor(() => !overlay() && !H.q(".upload-status") && !boxOpen(), { label, timeout: 30000 });
      await H.sleep(500);
    };
    const flows = {};

    // ---------------------------------------------------------------- 抖音
    flows.douyin_confirm_cancel = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await answerBox("确认发布", false);
      flushToasts("取消真实发布");
      await dump("douyin_confirm_cancel", "after");
      await saveFlowLog("douyin_confirm_cancel");
    };
    flows.douyin_stuck_cancel = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "stuck", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await answerBox("确认发布", true);
      await H.waitFor(() => H.q(".upload-status") && /50%/.test(H.text(H.q(".upload-status"))), { label: "进度面板 50%", timeout: 20000 });
      await H.sleep(400);
      note(`[overlay] ${overlay() ? H.text(overlay()) : "(无)"}`);
      note(`[upload-status] ${H.text(H.q(".upload-status"))}`);
      note(`[busy-ui] publish.disabled=${publishBtn().disabled} batch.disabled=${batchBtn().disabled} formDisabled=${H.q(".product-form").classList.contains("is-disabled")}`);
      await dump("douyin_stuck_cancel", "running");
      // 点击进度遮罩里的「取消上传」
      await H.click(btn(overlay(), "取消上传"), "取消上传");
      await H.waitFor(() => !overlay() && !H.q(".upload-status"), { label: "取消后结束", timeout: 20000 });
      await H.sleep(600);
      flushToasts("取消上传");
      await dump("douyin_stuck_cancel", "after_cancel");
      await saveFlowLog("douyin_stuck_cancel");
    };
    flows.douyin_success_publish = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await answerBox("确认发布", true);
      await answerBox("上传完成", true);
      await waitIdle();
      flushToasts("成功");
      await dump("douyin_success_publish", "after");
      await saveFlowLog("douyin_success_publish");
    };
    flows.douyin_stop_mode_success = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await answerBox("上传完成", true);
      await waitIdle();
      await dump("douyin_stop_mode_success", "after");
      await saveFlowLog("douyin_stop_mode_success");
    };
    flows.douyin_failed = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "failed", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await answerBox("上传失败", true);
      await waitIdle();
      await saveFlowLog("douyin_failed");
    };
    flows.douyin_start_errors = async () => {
      await setSubmitMode("stop");
      for (const mode of ["reject", "no_task_id", "http500"]) {
        await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: mode });
        await prepare();
        await resetLog();
        await H.click(publishBtn(), "开始抖音发布");
        await H.sleep(1500);
        flushToasts(`启动失败(${mode})`);
        note(`[busy-after ${mode}] overlay=${!!overlay()} status=${!!H.q(".upload-status")} publish.disabled=${publishBtn().disabled}`);
        await waitIdle();
        await saveFlowLog(`douyin_start_${mode}`);
      }
    };
    flows.douyin_flaky_resume = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "flaky", start_mode: "ok", flaky_failures: 5 });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始抖音发布");
      await H.waitFor(() => H.q(".upload-task-actions"), { label: "出现「重新读取进度」", timeout: 30000 });
      await H.sleep(400);
      note(`[paused-ui] ${H.text(H.q(".upload-task-actions"))} | status=${H.q(".upload-status") ? H.text(H.q(".upload-status")) : "(无)"} | overlay=${!!overlay()}`);
      await dump("douyin_flaky_resume", "paused");
      await H.ctl("mock", { flaky_failures: 0 });
      await H.click(btn(H.q(".upload-task-actions"), "重新读取进度"), "重新读取进度");
      await answerBox("上传完成", true);
      await waitIdle();
      await dump("douyin_flaky_resume", "after");
      await saveFlowLog("douyin_flaky_resume");
    };
    flows.batch_douyin = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(batchBtn(), "批量发布全部");
      await answerBox("批量发布确认", true);
      await answerBox("确认发布", true);
      await answerBox("上传完成", true);
      await waitIdle();
      await saveFlowLog("batch_douyin");
    };
    flows.batch_douyin_cancel = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(batchBtn(), "批量发布全部");
      await answerBox("批量发布确认", false);
      await dump("batch_douyin_cancel", "after");
      await saveFlowLog("batch_douyin_cancel");
    };

    // ---------------------------------------------------------------- 淘宝
    flows.taobao_fill_ok = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "douyin", mock_publish_save: true, upload_mode: "success", start_mode: "ok", taobao_mode: "fill_ok" });
      await prepare();
      await syncAccount("taobao");
      note(`[publish button] ${H.text(publishBtn())}`);
      await resetLog();
      await H.click(publishBtn(), "开始淘宝发布");
      await answerBox("上传完成", true);
      await waitIdle();
      await dump("taobao_fill_ok", "after");
      await saveFlowLog("taobao_fill_ok");
    };
    flows.taobao_fill_unverified = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "taobao", mock_publish_save: true, upload_mode: "success", start_mode: "ok", taobao_mode: "fill_unverified" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始淘宝发布");
      await answerBox("上传结果", true);
      await waitIdle();
      await saveFlowLog("taobao_fill_unverified");
    };
    flows.taobao_real_publish = async () => {
      await setSubmitMode("publish");
      await mock({ mock_platform: "taobao", mock_publish_save: true, upload_mode: "success", start_mode: "ok", taobao_mode: "publish_ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始淘宝发布");
      await answerBox("确认发布", true);
      await answerBox("发布完成", true);
      await waitIdle();
      await saveFlowLog("taobao_real_publish");
    };
    flows.taobao_failed = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "taobao", mock_publish_save: true, upload_mode: "failed", start_mode: "ok" });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始淘宝发布");
      await answerBox("上传失败", true);
      await waitIdle();
      await saveFlowLog("taobao_failed");
    };
    flows.taobao_start_http500_unknown = async () => {
      await setSubmitMode("stop");
      // 启动请求 500 → 结果未知；随后任务列表里有匹配的任务（创建时间晚于请求时间）→ 接回进度
      await mock({ mock_platform: "taobao", mock_publish_save: true, upload_mode: "success", start_mode: "http500", taobao_external: [] });
      await prepare();
      await resetLog();
      await H.click(publishBtn(), "开始淘宝发布");
      await H.sleep(1500);
      flushToasts("淘宝启动 500");
      note(`[unknown-start-ui] ${H.q(".upload-task-actions") ? H.text(H.q(".upload-task-actions")) : "(无)"} publish.disabled=${publishBtn().disabled}`);
      await dump("taobao_start_http500_unknown", "unknown");
      // 「重新读取进度」：仍读不到任务 → 提示
      await H.click(btn(H.q(".upload-task-actions"), "重新读取进度"), "重新读取进度(无任务)");
      await H.sleep(800);
      flushToasts("重新读取(无任务)");
      // 现在后端出现了匹配的任务（创建时间晚于启动请求）
      const prof = "mock-taobao";
      const rid = document.querySelector("#app").__vue_app__.config.globalProperties.$pinia._s.get("product").currentProductId;
      await H.ctl("mock", {
        start_mode: "ok",
        register_task: { id: "ext-taobao-1", platform: "taobao", record_id: rid, account_profile: prof, stop_before_submit: true, dry_run: false },
        taobao_external: [{
          task_id: "ext-taobao-1", platform: "taobao", account_profile: prof, record_id: rid, record_name: "mock", status: "running",
          progress: 30, message: "淘宝填写中(外部)", steps: [], dry_run: false, stop_before_submit: true, publish_confirmed: false,
          created_at: "2099-01-01T00:00:00", started_at: "2099-01-01T00:00:01",
        }],
      });
      await H.click(btn(H.q(".upload-task-actions"), "重新读取进度"), "重新读取进度(有任务)");
      await H.waitFor(() => H.q(".upload-status") || boxOpen(), { label: "接回任务", timeout: 15000 });
      await H.sleep(300);
      note(`[resumed] overlay=${!!overlay()} status=${H.q(".upload-status") ? H.text(H.q(".upload-status")).slice(0, 60) : "(无)"}`);
      await answerBox("外部上传完成", true);
      await waitIdle();
      await H.ctl("mock", { taobao_external: [] });
      await saveFlowLog("taobao_start_http500_unknown");
    };

    // ---------------------------------------------------------------- 小红书
    flows.xhs_single = async () => {
      await setSubmitMode("stop");
      for (const ok of [true, false]) {
        await mock({ mock_platform: "xiaohongshu", xhs_ok: ok });
        await syncAccount("xiaohongshu");
        await prepare();
        note(`[publish button] ${H.text(publishBtn())}`);
        await resetLog();
        await H.click(publishBtn(), "开始小红书千帆发布");
        await answerBox(ok ? "填表完成" : "填表结果", true);
        await waitIdle();
        await saveFlowLog(`xhs_single_${ok ? "ok" : "blocked"}`);
      }
    };
    flows.xhs_batch = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "xiaohongshu", xhs_ok: true });
      await syncAccount("xiaohongshu");
      await prepare();
      await resetLog();
      await H.click(batchBtn(), "批量发布全部");
      await answerBox("批量发布确认", true);
      await answerBox("上传完成", true);
      await waitIdle();
      await saveFlowLog("xhs_batch");
    };

    // ---------------------------------------------------------------- 外部任务接入
    flows.external_discovery = async () => {
      await setSubmitMode("stop");
      await mock({ mock_platform: "douyin", upload_mode: "stuck" });
      await syncAccount("douyin");
      await prepare();
      await resetLog();
      await H.ctl("mock", { external_tasks: [{
        task_id: "ext-douyin-1", record_id: 2, record_name: "mock", status: "running", progress: 20, message: "外部任务进行中",
        created_at: "2099-01-01T00:00:00", started_at: "2099-01-01T00:00:01",
      }] });
      await H.ctl("mock", { register_task: { id: "ext-douyin-1", platform: "douyin", record_id: 2, account_profile: "mock-douyin" } });
      restoreVisible();
      window.dispatchEvent(new Event("focus"));
      await H.waitFor(() => overlay() && H.q(".upload-status"), { label: "接上外部任务", timeout: 15000 });
      await H.sleep(600);
      note(`[external attached] overlay=${H.text(overlay()).slice(0, 80)} | status=${H.text(H.q(".upload-status")).slice(0, 60)}`);
      await dump("external_discovery", "attached");
      await H.ctl("mock", { external_tasks: [] });
      await H.click(btn(overlay(), "取消上传"), "取消外部上传");
      await H.waitFor(() => !overlay() && !H.q(".upload-status"), { label: "取消后结束", timeout: 20000 });
      await H.sleep(600);
      flushToasts("取消外部上传");
      await saveFlowLog("external_discovery");
      restoreVisible = H.quiet();
    };

    // ---------------------------------------------------------------- 运行
    await H.waitFor(() => items().length > 0 && /发布 · ID-/.test(H.text(H.q(".form-title"))) && detailIdle(), { label: "主页加载完成" });
    await H.sleep(1500);
    const order = only && only.length ? only : Object.keys(flows);
    for (const name of order) {
      note(`=== flow ${name}`);
      try {
        await flows[name]();
        await waitIdle(`流程 ${name} 收尾`);
      } catch (e) {
        note(`[FLOW ERROR] ${name}: ${e.message}`);
        note(`[overlay/boxes at failure] overlay=${!!overlay()} boxes=${boxes().map((b) => H.text(b)).join(" || ")} upload-status=${H.q(".upload-status") ? H.text(H.q(".upload-status")) : "(无)"} task-actions=${H.q(".upload-task-actions") ? H.text(H.q(".upload-task-actions")) : "(无)"}`);
        await H.save(`${phase}_home_publish_events.txt`, ev.join("\n"));
        throw e;
      }
    }
    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_home_publish_events.txt`, ev.join("\n"));
    return `events=${ev.length} saved=${JSON.stringify(info)} dpr=${devicePixelRatio}`;
  };
})();
