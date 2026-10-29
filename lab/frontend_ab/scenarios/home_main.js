// 主页主场景（不发布）：商品列表 / 选择 / 表单 / 填充 / 智能填充弹窗 / 保存 / 重复规格 / 删除 SKU / 右键菜单 / 图片管理 / 删除商品 / 清空全部。
// 前置：代理 mock_deletes=true（删除类接口只返回成功，不碰数据）；/save_info 走真实后端（隔离数据目录）。
(() => {
  window.__scn = window.__scn || {};
  window.__scn.home_main = async function (phase) {
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
    const ROOTS = [".product-manager", ".el-loading-mask", ".context-menu", ".el-dialog", ".el-message-box"];
    const dump = async (name) => note(await H.dumpAll(`${phase}_${name}.txt`, ROOTS));
    const btn = (root, text) => H.byText("button", text, root || document);
    const boxOpen = () => H.qa(".el-message-box").some(H.visible);
    const confirmBox = async (expect, accept = true) => {
      const box = await H.waitFor(() => H.qa(".el-message-box").find((b) => H.visible(b) && H.text(b).includes(expect)), { label: `确认框:${expect}` });
      note(`[messagebox] ${H.text(box)}`);
      await H.click(H.q(accept ? ".el-message-box__btns .el-button--primary" : ".el-message-box__btns .el-button:not(.el-button--primary)", box), "确认框按钮");
      await H.waitFor(() => !boxOpen(), { label: "确认框关闭" });
      await H.sleep(300);
    };
    const detailIdle = () => !H.q(".right-panel .el-loading-mask");
    const title = () => H.text(H.q(".form-title"));
    const items = () => H.qa(".product-item");
    const selectProduct = async (index) => {
      await H.click(items()[index], `商品 ${index}`);
      await H.sleep(200);
      await H.waitFor(detailIdle, { label: "商品详情加载完成" });
      await H.sleep(500);
    };
    const skuRows = () => H.qa(".sku-item");
    const input = (ph) => H.q(`.product-form input[placeholder="${ph}"]`);
    const skuPrices = () => skuRows().map((r) => H.q(".sku-price-input input", r).value).join(",");
    const skuNames = () => skuRows().map((r) => H.q(".sku-name-input input", r).value).join(",");

    // ---- 初始：自动选中第一个商品 ----
    await H.waitFor(() => items().length > 0 && /发布 · ID-/.test(title()) && detailIdle(), { label: "主页加载完成" });
    await H.sleep(1500);
    note(`[products] ${items().map((e) => H.text(e)).join(" | ")}`);
    note(`[auto-selected] ${title()}`);
    note(`[skus] ${skuNames()} / dupRows=${H.qa(".sku-item.has-duplicate").length}`);
    await dump("init");

    // ---- 选择第二个商品（测试船袜）----
    await selectProduct(1);
    note(`[selected] ${title()} skus=${skuNames()}`);
    await dump("product_boat");

    // ---- 表单填写 ----
    H.setValue(input("标题"), "测试袜子标题");
    H.setValue(input("卖点添加/备注说明"), "备注说明");
    H.setValue(input("设置库存"), "88");
    H.setValue(input("单价"), "10");
    await H.sleep(300);
    note(`[counter] ${H.text(H.q(".word-count"))}`);
    await dump("form_filled");
    H.setValue(input("标题"), "一".repeat(65));
    await H.sleep(300);
    note(`[counter-over] ${H.text(H.q(".word-count"))} over=${H.q(".word-count").classList.contains("over-limit")}`);
    H.setValue(input("标题"), "测试袜子标题");
    await H.sleep(200);

    // ---- 简单填充：无勾选 → 全部；有勾选 → 仅勾选 ----
    await H.click(btn(H.q(".price-row"), "填充"), "填充");
    await H.sleep(300);
    flushToasts("填充(全部)");
    note(`[prices after fill all] ${skuPrices()}`);
    await dump("fill_all");
    const thumbs = H.qa(".sku-thumbnail");
    await H.click(thumbs[0], "勾选 SKU1");
    await H.click(thumbs[1], "勾选 SKU2");
    await H.sleep(300);
    H.setValue(input("单价"), "7.5");
    await H.sleep(200);
    await H.click(btn(H.q(".price-row"), "填充"), "填充");
    await H.sleep(300);
    flushToasts("填充(勾选)");
    note(`[prices after fill selected] ${skuPrices()} selected=${H.qa(".sku-item.selected").length}`);
    await dump("fill_selected");
    await H.click(btn(H.q(".action-buttons"), "取消勾选"), "取消勾选");
    await H.sleep(300);
    flushToasts("取消勾选");
    note(`[selected after cancel] ${H.qa(".sku-item.selected").length}`);
    await dump("cancel_select");
    // 空价格填充
    H.setValue(input("单价"), "");
    await H.sleep(200);
    await H.click(btn(H.q(".price-row"), "填充"), "填充(空价格)");
    await H.sleep(300);
    flushToasts("填充(空价格)");

    // ---- 智能填充 ----
    await H.click(btn(H.q(".price-row"), "智能填充"), "智能填充(空价格)");
    await H.sleep(300);
    flushToasts("智能填充(空价格)");
    H.setValue(input("单价"), "10");
    await H.sleep(200);
    await H.click(btn(H.q(".price-row"), "智能填充"), "智能填充");
    await H.waitFor(() => H.qa(".el-dialog").some(H.visible), { label: "智能填充结果弹窗" });
    await H.sleep(600);
    flushToasts("智能填充");
    note(`[prices after smart fill] ${skuPrices()}`);
    note(`[pricing-dialog] ${H.text(H.qa(".el-dialog").find(H.visible)).slice(0, 400)}`);
    await dump("smart_fill_dialog");
    await H.click(btn(H.qa(".el-dialog").find(H.visible), "确定"), "确定");
    await H.sleep(600);
    note(`[dialog visible after close] ${H.qa(".el-dialog").some(H.visible)}`);
    await dump("smart_fill_closed");

    // ---- 保存 ----
    await H.click(btn(H.q(".price-row"), "保存"), "保存");
    await H.sleep(900);
    flushToasts("保存");
    await dump("saved");

    // ---- 重复规格：把 SKU2 改成和 SKU1 同名 → 保存 / 上传都被拦住 ----
    const dupNames = skuRows().map((r) => H.q(".sku-name-input input", r).value);
    H.setValue(H.q(".sku-name-input input", skuRows()[1]), dupNames[0]);
    await H.sleep(300);
    note(`[dup rows] ${H.qa(".sku-item.has-duplicate").length} inputs=${H.qa(".sku-name-input.is-duplicate").length}`);
    await dump("duplicate_names");
    await H.click(btn(H.q(".price-row"), "保存"), "保存(同名)");
    await H.sleep(400);
    flushToasts("保存(同名)");
    await H.click(btn(H.q(".action-buttons"), "开始抖音发布"), "开始抖音发布(同名)");
    await H.sleep(500);
    flushToasts("开始发布(同名)");
    for (const c of H.qa(".el-message .el-message__closeBtn")) c.click();
    await H.sleep(300);
    await dump("duplicate_blocked_save_publish");
    H.setValue(H.q(".sku-name-input input", skuRows()[1]), dupNames[1]);
    await H.sleep(300);
    note(`[dup rows after restore] ${H.qa(".sku-item.has-duplicate").length}`);

    // ---- 另一个商品：直接保存（后端校验不通过的真实分支）----
    await selectProduct(0);
    note(`[selected] ${title()} skus=${skuNames()}`);
    await H.click(btn(H.q(".price-row"), "保存"), "保存(重复规格)");
    await H.sleep(400);
    flushToasts("保存(重复规格)");
    note(`[duplicate-toast-present] ${H.qa(".el-message").length}`);
    for (const c of H.qa(".el-message .el-message__closeBtn")) c.click();
    await H.sleep(300);
    await dump("duplicate_blocked");

    // ---- 删除 SKU（测试船袜）----
    await selectProduct(1);
    const rowsBefore = skuRows().length;
    await H.click(btn(skuRows()[0], "删除"), "删除 SKU");
    await confirmBox("确定删除该SKU吗？");
    await H.sleep(700);
    flushToasts("删除 SKU");
    note(`[sku rows] ${rowsBefore} -> ${skuRows().length}`);
    await dump("sku_deleted");

    // ---- 右键菜单 / 图片管理 ----
    const target = items()[2];
    target.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 200, clientY: 300 }));
    await H.sleep(500);
    note(`[context-menu] ${H.q(".context-menu") ? H.text(H.q(".context-menu")) : "(未出现)"}`);
    await dump("context_menu");
    await H.click(btn(H.q(".context-menu"), "商品图片"), "商品图片");
    await H.waitFor(() => H.qa(".el-dialog").some(H.visible), { label: "图片管理弹窗" });
    await H.sleep(1200);
    note(`[media-dialog] ${H.text(H.qa(".el-dialog").find(H.visible)).slice(0, 300)}`);
    await dump("media_manager");
    const closeBtn = H.q(".el-dialog__headerbtn", H.qa(".el-dialog").find(H.visible));
    if (closeBtn) await H.click(closeBtn, "关闭图片管理");
    await H.sleep(600);
    note(`[dialog visible after close] ${H.qa(".el-dialog").some(H.visible)}`);

    // ---- 右键 → 删除商品 ----
    items()[2].dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 200, clientY: 300 }));
    await H.sleep(400);
    await H.click(btn(H.q(".context-menu"), "删除商品"), "删除商品");
    await confirmBox("确定删除该产品吗？");
    await H.sleep(700);
    flushToasts("删除商品");
    note(`[products after delete] ${items().length}: ${items().map((e) => H.text(e)).join(" | ")}`);
    await dump("product_deleted");

    // ---- 键盘打开右键菜单（Shift+F10 / ContextMenu 键）----
    items()[0].dispatchEvent(new KeyboardEvent("keydown", { key: "F10", shiftKey: true, bubbles: true, cancelable: true }));
    await H.sleep(400);
    note(`[keyboard-menu] ${H.q(".context-menu") ? "open" : "closed"}`);
    if (H.q(".context-menu")) document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await H.sleep(300);

    // ---- 清空全部 ----
    await H.click(btn(H.q(".action-buttons"), "清空全部"), "清空全部");
    await confirmBox("确定清空所有产品吗？");
    await H.sleep(700);
    flushToasts("清空全部");
    note(`[after clear all] products=${items().length} title=${title()} empty-tip=${H.q(".empty-tip") ? H.text(H.q(".empty-tip")) : "(无)"}`);
    await dump("cleared");

    // ---- 设置按钮 → 路由 ----
    await H.click(btn(H.q(".action-buttons"), "设置"), "设置");
    await H.sleep(800);
    note(`[after settings click] hash=${location.hash}`);

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_home_main_events.txt`, ev.join("\n"));
    const logInfo = await H.ctl(`save-log?name=${phase}_home_main_requests.jsonl`);
    return `events=${ev.length} saved=${JSON.stringify(info)} log=${JSON.stringify(logInfo)} dpr=${devicePixelRatio}`;
  };
})();
