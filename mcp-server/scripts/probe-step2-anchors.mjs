// Read-only: verify the exact step2 XPaths the publish code relies on against the
// currently-rendered classic form. No clicks, no writes — pure document.evaluate.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

// Selectors taken verbatim from app.py / src/utils.py publish flow.
const CODE_XPATHS = {
  // _PUBLISH_STEP2_SELECTORS (app.py:4884)
  "step2/价格与库存": '//div[@attr-field-id="价格与库存"]',
  "step2/goodsEditScrollContainer-价格库存": '//div[@id="goodsEditScrollContainer-价格库存"]',
  "step2/售卖价": '//div[@attr-field-id="售卖价"]',
  "step2/订单库存计数": '//div[@attr-field-id="订单库存计数"]',
  "step2/主图3:4": '//div[@attr-field-id="主图3:4"]',
  "step2/主图视频": '//div[@attr-field-id="主图视频"]',
  "step2/商品类目-修改": '//div[@attr-field-id="商品类目"]//*[text()="修改"]',
  "step2/类目属性": '//div[@attr-field-id="类目属性"]',
  // app.py field anchors
  "field/水洗标吊牌图": '//div[@attr-field-id="水洗标/吊牌图"]',
  "field/面料材质": '//div[@attr-field-id="面料材质"]',
  "field/商品详情": '//div[@attr-field-id="商品详情"]',
  "field/商品规格": '//div[@attr-field-id="商品规格"]',
  "field/白底图": '//div[@attr-field-id="白底图"]',
  "field/运费模板": '//div[@attr-field-id="运费模板"]',
  "field/商品状态": '//div[@attr-field-id="商品状态"]',
  "field/现货发货时间": '//div[@attr-field-id="现货发货时间"]',
  "field/使用品牌名": '//div[@attr-field-id="使用品牌名"]',
  "field/导购短标题": '//div[@attr-field-id="导购短标题"]',
  // src/utils.py:246 category text
  "utils/当前类目文本": '//div[@attr-field-id="商品类目"]//div[contains(@class,"style_currentCategory")]',
  "utils/类目文本含>": '//div[@attr-field-id="商品类目"]//*[contains(text(),">")]',
  // src/utils.py:2329 expand more
  "utils/展开更多": '//span[contains(@class,"style_categoryFolderBtn__") and contains(text(),"展开更多")]',
  // material composition (utils.py:361/369)
  "utils/材质combobox": '//div[@attr-field-id="面料材质"]//input[@role="combobox"]',
  "utils/材质del": '//div[@attr-field-id="面料材质"]//span[contains(@class,"styles_del__")]',
  "utils/aurora多选": '//div[@attr-field-id="面料材质"]//div[contains(@class,"aurora-select-multiple")]',
  // sku (app.py / utils.py)
  "sku/skuValue-颜色分类": '//*[@id="skuValue-颜色分类"]',
  "sku/添加规格图": '//*[normalize-space(text())="添加规格图"]',
  // detail upload (app.py:5360)
  "detail/商品详情-file-label": '//div[@attr-field-id="商品详情"]//label[.//input[@type="file"]]',
  "detail/商品详情-material-upload": '//div[@attr-field-id="商品详情"]//div[contains(@class,"material-upload-button")]',
  // bottom actions
  "action/发布商品": '//*[normalize-space(text())="发布商品"]',
  "action/保存草稿": '//*[normalize-space(text())="保存草稿"]',
  "action/上架": '//*[normalize-space(text())="上架"]',
  "action/48小时": '//*[normalize-space(text())="48小时"]',
  "action/均码": '//*[normalize-space(text())="均码"]',
};

const EVAL = `(() => {
  const xpaths = ${JSON.stringify(CODE_XPATHS)};
  const visible = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const out = {};
  for (const [name, xp] of Object.entries(xpaths)) {
    try {
      const snap = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      let vis = 0;
      for (let i = 0; i < snap.snapshotLength; i++) if (visible(snap.snapshotItem(i))) vis++;
      const first = snap.snapshotLength ? snap.snapshotItem(0) : null;
      out[name] = {
        count: snap.snapshotLength,
        visible: vis,
        firstTag: first && first.tagName ? first.tagName.toLowerCase() : null,
        firstText: first ? (first.innerText || first.textContent || '').trim().slice(0, 24) : null,
      };
    } catch (e) { out[name] = { error: String(e && e.message || e) }; }
  }
  return { href: location.href, results: out };
})()`;

function callT(client, method, params, ms = 6000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const r = await callT(client, "Runtime.evaluate", { expression: EVAL, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return { ok: false, error: r.exceptionDetails.text };
    return { ok: true, ...r.result.value };
  });
  // compact console summary
  const rows = Object.entries(result.results || {}).map(([k, v]) => ({
    anchor: k,
    count: v.count ?? "ERR",
    visible: v.visible ?? "-",
    status: v.error ? "ERROR" : (v.count > 0 ? "HIT" : "MISS"),
  }));
  console.log(JSON.stringify({ ok: result.ok, href: result.href, rows }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
