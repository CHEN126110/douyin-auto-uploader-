// 设置页主场景：5 个 Tab 的初始快照 + 各 Tab 的典型交互 + 保存。
// 在 /#/settings 直接加载后运行（此时没有店铺会话，运费模板走「账户未确认」分支）。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.settings_main = async function (phase) {
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
    const dump = async (name) => { note(await H.dump(`${phase}_${name}.txt`, ".settings-page")); note(`[scroll] ${name}: tabsContent.scrollTop=${H.q(".el-tabs__content").scrollTop}`); };
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

    await H.waitFor(() => H.q(".settings-panel") && !H.q(".settings-panel .el-loading-mask"), { label: "设置面板加载完成" });
    await H.sleep(1500);
    note(`[footer-init] ${H.text(H.q(".settings-footer"))}`);

    // ---- A. 各 Tab 初始快照 ----
    for (const t of ["pricing", "model", "automation", "mcp", "about"]) {
      await tab(t);
      await dump(`init_${t}`);
    }

    // ---- B. 价格设置 ----
    await tab("pricing");
    await H.click(btn(H.q("#pane-pricing"), "添加成本项"), "添加成本项");
    await H.sleep(450);
    await dump("pricing_addform_open");
    // 先点「确认添加」不填名称 → 应提示
    await H.click(btn(H.q(".add-cost-form"), "确认添加"), "确认添加(空)");
    await H.sleep(300);
    flushToasts("空名称添加");
    H.setValue(H.q('.add-cost-form input[placeholder="如：包装费"]'), "测试成本项");
    H.setValue(H.q('.add-cost-form input[type="number"]'), "2.5");
    H.setValue(H.q('.add-cost-form input[placeholder="简要说明此成本项的用途"]'), "验证用");
    await H.sleep(200);
    await dump("pricing_addform_filled");
    await H.click(btn(H.q(".add-cost-form"), "确认添加"), "确认添加");
    await H.sleep(600);
    flushToasts("添加成本项");
    await dump("pricing_after_add");
    // 编辑第一行
    await H.click(btn(H.qa(".cost-item-row")[0], "编辑"), "编辑");
    await H.sleep(300);
    await dump("pricing_editing");
    H.setValue(H.q(".cost-item-row.editing .edit-name input"), "改名运费");
    H.setValue(H.q(".cost-item-row.editing .edit-value input"), "4");
    await H.sleep(200);
    await H.click(btn(H.q(".cost-item-row.editing"), "完成"), "完成");
    await H.sleep(300);
    await dump("pricing_after_edit");
    // 删除最后一行
    const rows = H.qa(".cost-item-row");
    await H.click(btn(rows[rows.length - 1], "删除"), "删除");
    await confirmBox("确定删除该成本项吗？");
    flushToasts("删除成本项");
    await dump("pricing_after_delete");
    H.setValue(H.q(".config-input input"), "35");
    await H.sleep(200);
    await dump("pricing_margin_changed");

    // ---- C. 智能模型 ----
    await tab("model");
    const firstModel = H.qa(".model-config-item")[0];
    await H.click(H.q(".el-switch", firstModel), "启用开关");
    await H.sleep(300);
    await H.click(btn(firstModel, "获取模型"), "获取模型(空密钥)");
    await H.sleep(300);
    flushToasts("空密钥获取模型");
    await H.click(btn(firstModel, "测试"), "测试(空密钥)");
    await H.sleep(300);
    flushToasts("空密钥测试");
    H.setValue(H.q('input[type="password"]', firstModel), "sk-test-not-real");
    await H.sleep(200);
    await H.click(btn(firstModel, "获取模型"), "获取模型");
    await H.sleep(700);
    flushToasts("获取模型");
    await H.click(btn(firstModel, "测试"), "测试");
    await H.sleep(700);
    flushToasts("测试连接");
    await dump("model_after_fetch_test");
    H.setValue(H.q('.add-model-form input[placeholder^="给这个配置起个名字"]'), "我的测试配置");
    await H.sleep(200);
    await H.click(btn(H.q(".add-model-form"), "添加模型"), "添加模型");
    await H.sleep(500);
    flushToasts("添加模型");
    await dump("model_after_add");
    const models = H.qa(".model-config-item");
    await H.click(btn(models[models.length - 1], "删除"), "删除模型");
    await confirmBox("确定删除该模型配置吗？");
    flushToasts("删除模型");
    await dump("model_after_delete");

    // ---- D. 自动化设置 ----
    await tab("automation");
    await H.click(H.byText("label.mode-card", "极速发布"), "极速发布");
    await H.click(H.byText("label.mode-card", "只填写不发布"), "只填写不发布");
    const prefRows = H.qa(".capture-pref-row");
    await H.click(H.byText("label.el-radio-button", "协议采集", prefRows[0]), "1688 协议采集");
    await H.sleep(400);
    await dump("automation_modes_changed");
    // 材质：含量改成 80 → 合计 105%，保存应被拦截
    H.setValue(H.q(".material-item .material-percentage-input input"), "80");
    await H.sleep(300);
    await dump("automation_material_invalid");
    await tab("pricing");
    note(`[scroll-probe] after tab(pricing): ${H.q(".el-tabs__content").scrollTop} active=${document.activeElement && (document.activeElement.tagName + "." + document.activeElement.className).slice(0, 80)}`);
    await H.click(btn(H.q(".settings-footer"), "保存设置"), "保存(材质无效)");
    note(`[scroll-probe] right after save click: ${H.q(".el-tabs__content").scrollTop}`);
    await H.sleep(600);
    note(`[scroll-probe] 600ms after save click: ${H.q(".el-tabs__content").scrollTop}`);
    flushToasts("材质无效时保存");
    note(`[active-tab-after-invalid-save] ${H.text(H.q(".el-tabs__item.is-active"))}`);
    await dump("automation_after_invalid_save");
    // 空名称添加材质
    await H.click(btn(H.q(".add-material-form"), "添加材质"), "添加材质(空)");
    await H.sleep(300);
    flushToasts("空材质添加");
    // 复原含量
    H.setValue(H.q(".material-item .material-percentage-input input"), "75");
    await H.sleep(300);
    // 水洗标：选择图片依赖 Tauri 对话框，浏览器里应走失败分支
    await H.click(btn(H.q("#pane-automation"), "选择水洗标/吊牌图"), "选择水洗标");
    await H.sleep(800);
    flushToasts("选择水洗标/吊牌图");
    // 引导状态重置
    localStorage.setItem("onboarding_completed", "true");
    await H.click(btn(H.q("#pane-automation"), "重置引导状态"), "重置引导状态");
    await H.sleep(300);
    flushToasts("重置引导状态");
    note(`[localStorage after reset] onboarding_completed=${localStorage.getItem("onboarding_completed")}`);
    localStorage.setItem("onboarding_completed", "true");
    await dump("automation_final");

    // ---- E. 高级集成 / 关于 ----
    await tab("mcp");
    await H.click(btn(H.q("#pane-mcp"), "复制命令"), "复制命令");
    await H.sleep(500);
    flushToasts("复制命令");
    await dump("mcp_after_copy");
    await tab("about");
    await H.click(btn(H.q("#pane-about"), "检查更新"), "检查更新");
    await H.sleep(1200);
    flushToasts("检查更新");
    await dump("about_after_check");

    // ---- F. 保存 ----
    note(`[footer-before-save] ${H.text(H.q(".settings-footer"))}`);
    await H.click(btn(H.q(".settings-footer"), "保存设置"), "保存设置");
    await H.sleep(1000);
    flushToasts("保存设置");
    note(`[footer-after-save] ${H.text(H.q(".settings-footer"))}`);
    await dump("after_save");
    await tab("pricing");
    await dump("final_pricing");

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_settings_main_events.txt`, ev.join("\n"));
    const logInfo = await H.ctl(`save-log?name=${phase}_settings_main_requests.jsonl`);
    return `events=${ev.length} saved=${JSON.stringify(info)} log=${JSON.stringify(logInfo)} dpr=${devicePixelRatio}`;
  };
})();
