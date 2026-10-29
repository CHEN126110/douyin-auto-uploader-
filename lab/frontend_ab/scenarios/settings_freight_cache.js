// 设置页「运费模板名单」缓存场景：读取失败时名单怎么变、保存时发什么、换账户时怎么变。
// 起点和 settings_session 一样（从主页进设置，带抖音假会话），前置：
//   .\ab.ps1 prep，再 POST /__ctl/mock {"mock_platform":"douyin","freight_mode":"ok"}。
//
// 2026-10-19 修复前后的区别就在这里（snapshot 里看不出来：下拉选项在 body 下的浮层里，不在 .settings-page 内）：
//   修复前：每次读取一开始就把 shippingTemplates 清空，读不到店铺时名单是 []，此时保存会把 [] 发给后端，
//           后端退回默认名单——已缓存的名单被缩成「默认值 + 当前选中项」；
//   修复后：只有读取成功才改写名单，读取失败时保持原样。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.settings_freight_cache = async function (phase) {
    const H = window.__H;
    // 页面可见时 App.vue 会因 focus / visibilitychange 反复静默刷新商品列表，插进请求日志；
    // 让页面自认「不可见」，结果就不再取决于浏览器窗格当前有没有显示出来。
    H.quiet();
    const ev = [];
    const note = (s) => ev.push(s);

    const tab = async (name) => { await H.click(H.q(`#tab-${name}`), name); await H.sleep(450); };
    const btn = (root, text) => H.byText("button", text, root || document);
    const setMock = (patch) => H.ctl("mock", patch);
    const footer = () => H.text(H.q(".settings-footer")).replace(/\s+/g, "");
    const source = () => H.text(H.q(".freight-source"));
    const reread = async (label) => {
      await H.click(btn(H.q("#pane-automation"), "重新读取"), "重新读取");
      await H.sleep(900);
      note(`[reread ${label}] source="${source()}" footer=${footer()}`);
    };
    // 展开运费模板下拉，读出当前有哪些选项，再收起。
    const options = async (label) => {
      const wrapper = H.q("#pane-automation .template-select .el-select__wrapper") || H.q("#pane-automation .template-select");
      await H.click(wrapper, "展开下拉");
      await H.sleep(400);
      const items = H.qa(".el-select-dropdown__item").filter(H.visible).map(H.text);
      const empty = H.qa(".el-select-dropdown__empty").filter(H.visible).map(H.text);
      await H.click(wrapper, "收起下拉");
      await H.sleep(300);
      note(`[options ${label}] ${JSON.stringify(items)}${empty.length ? " empty=" + JSON.stringify(empty) : ""}`);
      return items;
    };
    const lastSave = async () => {
      const log = (await H.ctl("log")).log.filter((e) => e.method === "POST" && e.path === "/settings");
      const last = log[log.length - 1];
      const ac = last && last.body && last.body.automation_config;
      note(`[saved body] shipping_template=${JSON.stringify(ac && ac.shipping_template)} shipping_templates=${JSON.stringify(ac && ac.shipping_templates)} (保存请求 ${log.length} 次)`);
    };

    // ---- 主页 → 设置（带会话）----
    await H.waitFor(() => H.q(".product-manager"), { label: "主页" });
    await H.sleep(2500); // 等 ShopStatusBar 读到会话
    await H.click(btn(H.q(".product-manager"), "设置"), "设置按钮");
    await H.waitFor(() => H.q(".settings-panel") && !H.q(".settings-panel .el-loading-mask"), { label: "设置面板" });
    await H.sleep(1500);
    await tab("automation");
    note(`[open] source="${source()}" footer=${footer()}`);
    await options("打开设置页后（读取成功）");

    // ---- 用户选了另一个模板（这才是真正的用户改动），然后读取失败，再保存 ----
    const useBtns = H.qa(".template-item .template-use-btn");
    note(`[use-buttons] ${useBtns.length}`);
    if (useBtns.length) await H.click(useBtns[0], "使用");
    await H.sleep(300);
    note(`[after use] footer=${footer()}`);
    await setMock({ freight_mode: "http500" });
    await reread("接口 500");
    await options("读取失败(500)之后");
    await H.ctl("reset");
    await H.click(btn(H.q(".settings-footer"), "保存设置"), "保存设置");
    await H.sleep(900);
    await lastSave();
    note(`[after save] footer=${footer()}`);

    // ---- 需要发布页（没读到，不是没有模板）----
    await setMock({ freight_mode: "need_publish_page" });
    await reread("需要发布页");
    await options("需要发布页之后");

    // ---- 读到另一批名单（缺少原来的「中通包邮」）：以店铺为准，名单应整体换成新的 ----
    await setMock({ freight_mode: "missing" });
    await reread("读取成功(另一批)");
    await options("读到另一批之后");

    // ---- 换账户 + 新账户读取失败：名单是上一个账户的，会不会被留着 ----
    const store = document.querySelector("#app").__vue_app__.config.globalProperties.$pinia._s.get("product");
    const cur = store.currentShopSession;
    await setMock({ freight_mode: "http500" });
    store.setShopSession({ ...cur, active_profile: "mock-douyin-other", active_profile_label: "另一个抖音账户" });
    await H.sleep(1200);
    note(`[account switched, read fails] source="${source()}" footer=${footer()}`);
    await options("换账户且读取失败之后");

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_settings_freight_cache_events.txt`, ev.join("\n"));
    const logInfo = await H.ctl(`save-log?name=${phase}_settings_freight_cache_requests.jsonl`);
    return `events=${ev.length} saved=${JSON.stringify(info)} log=${JSON.stringify(logInfo)} dpr=${devicePixelRatio}`;
  };
})();
