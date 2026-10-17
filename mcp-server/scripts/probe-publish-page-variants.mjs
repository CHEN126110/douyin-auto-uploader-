// Read-only: enumerate every FXG publish tab on the CDP endpoint and dump a
// normalized "page variant" signature for each.
//
// RED LINE: this script only reads the DOM via Runtime.evaluate. It never
// navigates, clicks, uploads, saves or submits anything.
//
// Usage:
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9500/json/list'
//   node mcp-server/scripts/probe-publish-page-variants.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";
const ONLY_PAGE = (process.env.ONLY_PAGE || "1") !== "0";

const PROBE = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const body = document.body ? (document.body.innerText || '') : '';
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  const xp = (expr) => {
    try {
      const r = document.evaluate(expr, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const out = [];
      for (let i = 0; i < r.snapshotLength; i++) out.push(r.snapshotItem(i));
      return out;
    } catch (e) { return []; }
  };
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const desc = (el) => {
    if (!el || el.nodeType !== 1) return null;
    let handlerSelf = false;
    const pk = Object.keys(el).find((k) => k.startsWith('__reactProps$'));
    if (pk && el[pk] && typeof el[pk].onClick === 'function') handlerSelf = true;
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 70),
      text: norm(el.innerText || el.textContent).slice(0, 24),
      handlerSelf,
      visible: vis(el),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    };
  };

  // --- variant markers -------------------------------------------------
  const markers = {
    // 2026-08 documented AI entry (file-only, "下一步，生成商品")
    aiEntry202608: /上传资料越完整|任意截图|下一步，生成商品/.test(body),
    // the variant in the user's screenshot
    aiConfirmCard: /确认信息，继续生成/.test(body),
    materialSection: /商品材料/.test(body),
    suggestSection: /建议补充/.test(body),
    returnOldText: /返回旧版/.test(body),
    returnNewText: /返回新版|体验新版/.test(body),
    nextStepText: /下一步/.test(body),
    publishBtnText: /发布商品/.test(body),
    saveDraftText: /保存草稿/.test(body),
    hasPriceStockContainer: !!document.querySelector('[id^="goodsEditScrollContainer"]'),
    hasCategorySelectorV2: !!document.querySelector('[class*="categorySelectorV2"]'),
  };

  // --- CTA candidates the automation looks for -------------------------
  const cta = {
    next_button_span: xp('//button[.//span[text()="下一步"]]').filter(vis).length,
    next_any_text: xp('//*[normalize-space(text())="下一步"]').filter(vis).length,
    confirm_generate_any: xp('//*[normalize-space(text())="确认信息，继续生成"]').filter(vis).length,
    publish_span_parent: xp('//span[text()="发布商品"]/..').filter(vis).length,
    publish_any: xp('//*[normalize-space(text())="发布商品"]').filter(vis).length,
    return_old_div: xp('//div[normalize-space(text())="返回旧版"]').filter(vis).length,
    return_old_any: xp('//*[normalize-space(text())="返回旧版"]').filter(vis).length,
  };

  // --- step detectors used by app.py ----------------------------------
  const step1 = [
    '//button[.//span[text()="下一步"]]',
    '//span[text()="下一步"]/..',
    '//div[contains(@class,"categorySelectorV2")]',
    '//span[text()="手动选择"]/..',
  ].some((x) => xp(x).some(vis));
  const step2 = [
    '//div[@attr-field-id="价格与库存"]',
    '//div[@id="goodsEditScrollContainer-价格库存"]',
    '//div[@attr-field-id="售卖价"]',
    '//div[@attr-field-id="订单库存计数"]',
    '//div[@attr-field-id="主图3:4"]',
    '//div[@attr-field-id="主图视频"]',
    '//div[@attr-field-id="商品类目"]//*[text()="修改"]',
    '//div[@attr-field-id="类目属性"]',
  ].some((x) => xp(x).some(vis));
  const titleField = document.querySelector('[attr-field-id="商品标题"]');
  let titleReady = false;
  if (titleField) {
    titleReady = vis(titleField.querySelector('#pg-title-input') || titleField.querySelector('input') || titleField.querySelector('textarea'));
  }
  const appStage = step2 ? 'step2' : (titleReady || step1) ? 'step1' : 'unknown';

  // --- title input state ----------------------------------------------
  const tInp = document.querySelector('#pg-title-input');
  const titleState = tInp ? { exists: true, value: (tInp.value || '').slice(0, 80), maxLength: tInp.getAttribute('maxlength') } : { exists: false };

  // --- visible buttons -------------------------------------------------
  const buttons = q('button').filter(vis).map((b) => norm(b.innerText)).filter(Boolean).slice(0, 40);

  // --- validation / error surface --------------------------------------
  const errSelectors = ['[class*="ecom-g-message"]', '[class*="error"]', '[class*="Error"]', '[class*="toast"]', '[class*="Toast"]', '[role="alert"]'];
  const errs = [];
  errSelectors.forEach((sel) => {
    q(sel).forEach((n) => {
      const t = norm(n.innerText);
      if (t && t.length <= 120 && vis(n)) errs.push({ sel, text: t });
    });
  });

  // --- form field ids --------------------------------------------------
  const fieldIds = q('[attr-field-id]').map((e) => e.getAttribute('attr-field-id'));

  // --- category text ---------------------------------------------------
  const catCands = xp('//*[contains(@class,"style_currentCategory")]').map((n) => norm(n.innerText));
  const catLike = catCands.length ? catCands : (body.match(/[^\\n]{0,10}>[^\\n]{0,20}>[^\\n]{0,20}>[^\\n]{0,20}/g) || []).slice(0, 2);

  // --- upload inputs ---------------------------------------------------
  const fileInputs = q('input[type=file]').map((e) => ({ accept: e.getAttribute('accept') || '', multiple: e.hasAttribute('multiple') }));

  return {
    href: location.href,
    title: document.title,
    bodyLen: body.length,
    variantGuess: markers.aiConfirmCard ? 'AI_CONFIRM_CARD'
      : markers.aiEntry202608 ? 'AI_ENTRY_202608'
      : appStage === 'step2' ? 'CLASSIC_STEP2'
      : appStage === 'step1' ? 'CLASSIC_STEP1'
      : 'UNKNOWN',
    appStage,
    markers, cta, titleState, buttons, fieldCount: fieldIds.length,
    fieldIdsSample: fieldIds.slice(0, 70), category: catLike, fileInputs: fileInputs.slice(0, 12),
    errors: errs.slice(0, 15),
    returnOldDesc: (xp('//*[normalize-space(text())="返回旧版"]')[0]) ? desc(xp('//*[normalize-space(text())="返回旧版"]')[0]) : null,
    nextDesc: (xp('//*[normalize-space(text())="下一步"]')[0]) ? desc(xp('//*[normalize-space(text())="下一步"]')[0]) : null,
    confirmGenerateDesc: (xp('//*[normalize-space(text())="确认信息，继续生成"]')[0]) ? desc(xp('//*[normalize-space(text())="确认信息，继续生成"]')[0]) : null,
    headText: norm(body).slice(0, 400),
  };
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
const selected = ONLY_PAGE ? pages : pages;

console.error(`# 命中 ${pages.length} 个目标(过滤 ${URL_FILTER})`);

const results = [];
for (const t of selected) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: true }),
      delay(15000).then(() => { throw new Error("timeout"); }),
    ]);
    if (res.exceptionDetails) {
      const d = res.exceptionDetails;
      results.push({
        targetId: t.id,
        url: t.url,
        ok: false,
        error: (d.exception && (d.exception.description || d.exception.value)) || d.text,
        line: d.lineNumber,
        column: d.columnNumber,
      });
    } else {
      results.push({ targetId: t.id, ok: true, ...res.result.value });
    }
  } catch (e) {
    results.push({ targetId: t.id, url: t.url, ok: false, error: e instanceof Error ? e.message : String(e) });
  } finally {
    client.close();
  }
}

console.log(JSON.stringify({ listUrl: process.env.DOUYIN_CDP_LIST_URL || "(default)", targetCount: pages.length, results }, null, 2));
