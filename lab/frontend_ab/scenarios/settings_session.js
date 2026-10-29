// 设置页（有店铺会话）场景：运费模板读取各分支 + 水洗标预览 / 清空 + 会话切换后的重新读取。
// 从主页进入（SPA 跳转，Pinia 里已有店铺会话），前置条件由 Bash 侧准备：
//   代理 mock_platform=douyin、freight_mode=ok；后端设置里已有一张水洗标图片。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.settings_session = async function (phase) {
    const H = window.__H;
    // 页面可见时 App.vue 会因 focus / visibilitychange 反复静默刷新商品列表，插进请求日志；
    // 让页面自认「不可见」，结果就不再取决于浏览器窗格当前有没有显示出来。
    H.quiet();
    const ev = [];
    const note = (s) => ev.push(s);

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
    const dump = async (name) => { note(await H.dump(`${phase}_${name}.txt`, ".settings-page")); };
    const tab = async (name) => { await H.click(H.q(`#tab-${name}`), name); await H.sleep(450); };
    const btn = (root, text) => H.byText("button", text, root || document);
    const boxOpen = () => H.qa(".el-message-box").some(H.visible);
    const confirmBox = async (expect) => {
      const box = await H.waitFor(() => H.qa(".el-message-box").find((b) => H.visible(b) && H.text(b).includes(expect)), { label: `确认框:${expect}` });
      note(`[messagebox] ${H.text(box)}`);
      await H.click(H.q(".el-message-box__btns .el-button--primary", box), "确认");
      await H.waitFor(() => !boxOpen(), { label: "确认框关闭" });
      await H.sleep(300);
    };
    const setMock = (patch) => H.ctl("mock", patch);
    const reread = async (label) => {
      await H.click(btn(H.q("#pane-automation"), "重新读取"), "重新读取");
      await H.sleep(900);
      flushToasts(label);
    };
    const goHome = async () => {
      await H.click(btn(H.q(".settings-page"), "返回"), "返回");
      await H.waitFor(() => H.q(".product-manager") && H.text(H.q(".shop-status-bar, .left-panel") || document.body).length > 0, { label: "主页" });
      await H.sleep(1200);
    };
    const goSettings = async () => {
      await H.click(btn(H.q(".product-manager"), "设置"), "设置按钮");
      await H.waitFor(() => H.q(".settings-panel") && !H.q(".settings-panel .el-loading-mask"), { label: "设置面板" });
      await H.sleep(1500);
    };

    // ---- 主页 → 设置（带会话）----
    await H.waitFor(() => H.q(".product-manager"), { label: "主页" });
    await H.sleep(2500); // 等 ShopStatusBar 读到会话
    note(`[session] ${H.text(H.q(".left-panel"))}`.slice(0, 160));
    await goSettings();
    await tab("automation");
    note(`[footer-init] ${H.text(H.q(".settings-footer"))}`);
    await dump("session_init_automation");

    // ---- 运费模板：ok / 选择 / 缺失 / 需发布页 / 500 ----
    await reread("读取成功(ok)");
    await dump("freight_ok");
    // 点第二个模板的「使用」
    const useBtns = H.qa(".template-item .template-use-btn");
    note(`[use-buttons] ${useBtns.length}`);
    if (useBtns.length) await H.click(useBtns[0], "使用");
    await H.sleep(300);
    await dump("freight_selected_other");
    await setMock({ freight_mode: "missing" });
    await reread("读取成功(缺少已选模板)");
    await dump("freight_missing_selected");
    await setMock({ freight_mode: "need_publish_page" });
    await reread("需要发布页");
    await dump("freight_need_publish_page");
    await setMock({ freight_mode: "http500" });
    await reread("接口 500");
    await dump("freight_http500");
    await setMock({ freight_mode: "ok" });
    await reread("再次成功");

    // ---- 水洗标：预览 / 清空 ----
    await dump("washlabel_with_image");
    const img = H.q(".certificate-preview-img");
    note(`[washlabel-img] ${img ? img.getAttribute("src").replace(/t=\d+/, "t=*") : "(无)"}`);
    const clearBtn = btn(H.q("#pane-automation"), "清空图片");
    note(`[clear-disabled] ${clearBtn && clearBtn.disabled}`);
    await H.click(clearBtn, "清空图片");
    await confirmBox("确定清空当前水洗标/吊牌图吗？");
    flushToasts("清空水洗标");
    await dump("washlabel_cleared");

    // ---- 保存（含已读取的运费模板与清空后的水洗标）----
    await H.click(btn(H.q(".settings-footer"), "保存设置"), "保存设置");
    await H.sleep(900);
    flushToasts("保存");
    await dump("after_save");

    // ---- 返回主页，换成淘宝账户，再进设置 ----
    await setMock({ mock_platform: "taobao", freight_mode: "ok" });
    await goHome();
    note(`[home-taobao] ${H.text(H.q(".left-panel")).slice(0, 60)}`);
    await goSettings();
    await tab("automation");
    await dump("taobao_session_automation");

    // ---- 设置页打开期间会话变化：运费模板应自动重新读取（watch 接线）----
    const store = document.querySelector("#app").__vue_app__.config.globalProperties.$pinia._s.get("product");
    const cur = store.currentShopSession;
    note(`[store-session-before] ${cur && cur.platform}/${cur && cur.active_profile}`);
    await H.ctl(`save-log?name=${phase}_settings_session_requests.jsonl`);
    await H.ctl("reset");
    store.setShopSession({ ...cur, active_profile: "mock-taobao-other", active_profile_label: "另一个淘宝账户" });
    await H.sleep(1200);
    const log = await H.ctl("log");
    note(`[freight-requests-after-session-change] ${log.log.filter((e) => e.path === "/api/shop/freight-templates").length}`);
    await dump("after_session_change");
    store.setShopSession(null);
    await H.sleep(600);
    await dump("after_session_cleared");

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_settings_session_events.txt`, ev.join("\n"));
    const logInfo = await H.ctl(`save-log?name=${phase}_settings_session_requests_tail.jsonl`);
    return `events=${ev.length} saved=${JSON.stringify(info)} log=${JSON.stringify(logInfo)} dpr=${devicePixelRatio}`;
  };
})();
