// Read-only: click "返回旧版" then snapshot the classic publish form DOM.
// Only a view switch + DOM read. No upload / save / submit is triggered.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

const CLICK_OLD = `(() => {
  const all = Array.from(document.querySelectorAll('span, button, div, a'));
  const el = all.find((n) => (n.innerText || n.textContent || '').trim() === '返回旧版');
  if (!el) return { clicked: false, reason: 'no 返回旧版 element' };
  el.click(); // React onClick is bound on the element itself (handlerLevel 0)
  return { clicked: true, cls: (typeof el.className === 'string' ? el.className : '') };
})()`;

// If a confirm modal ("确定返回旧版") appears, click its confirm button.
const CONFIRM_MODAL = `(() => {
  const modals = Array.from(document.querySelectorAll('[class*="modal"], [class*="Modal"], [role="dialog"]'));
  for (const m of modals) {
    const btns = Array.from(m.querySelectorAll('button, [role="button"], a'));
    const ok = btns.find((b) => /^(确定|确认|返回旧版|好的|继续)$/.test((b.innerText || b.textContent || '').trim()));
    if (ok) { ok.click(); return { confirmed: true, label: (ok.innerText || '').trim() }; }
  }
  return { confirmed: false };
})()`;

const SNAPSHOT = `(() => {
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  const txt = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
  const byText = (needle) => q('span, button, div, a, label')
    .some((n) => txt(n) === needle);
  const containsText = (needle) => (document.body.innerText || '').includes(needle);

  const fieldIds = q('[attr-field-id]').map((el) => el.getAttribute('attr-field-id'));
  const scrollContainers = q('[id^="goodsEditScrollContainer"]').map((el) => el.id);

  const titleField = document.querySelector('[attr-field-id="商品标题"]');
  const titleInput = document.querySelector('#pg-title-input')
    || (titleField && titleField.querySelector('input, textarea'));

  const step1 = {
    hasNextButton: q('button').some((b) => /下一步/.test(txt(b))) || byText('下一步'),
    hasCategorySelectorV2: q('[class*="categorySelectorV2"]').length > 0,
    hasManualSelect: byText('手动选择'),
  };

  const step2Anchors = ['价格与库存','售卖价','订单库存计数','主图3:4','主图视频','商品类目','类目属性','水洗标/吊牌图','面料材质','商品详情','商品规格']
    .map((name) => ({ name, present: !!document.querySelector('[attr-field-id="' + name + '"]') }));

  const publishBtns = q('button').map((b) => txt(b)).filter((t) => t && /发布|保存|提交|下一步|上一步|上架/.test(t)).slice(0, 20);

  return {
    href: location.href,
    title: document.title,
    stillAiEntry: containsText('生成商品') && containsText('上传资料'),
    fieldIdCount: fieldIds.length,
    fieldIds,
    scrollContainers,
    titleFieldPresent: !!titleField,
    titleInputPresent: !!titleInput,
    titleInputId: titleInput ? (titleInput.id || '') : '',
    step1,
    step2Anchors,
    publishBtns,
  };
})()`;

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await client.call("Runtime.enable").catch(() => {});
    const evalOnce = async (expr) => {
      const r = await client.call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
      if (r.exceptionDetails) return { __evalError: r.exceptionDetails.text || 'eval error' };
      return r.result.value;
    };

    const before = await evalOnce(SNAPSHOT);
    let clickRes = { clicked: false };
    if (before && before.stillAiEntry) {
      clickRes = await evalOnce(CLICK_OLD);
      // poll until classic form appears (attr-field-id present) or timeout
      let confirmRes = null;
      for (let i = 0; i < 24; i++) {
        await delay(500);
        if (i === 1 || i === 3) confirmRes = await evalOnce(CONFIRM_MODAL);
        const snap = await evalOnce(SNAPSHOT);
        if (snap && (snap.titleFieldPresent || snap.fieldIdCount > 0 || !snap.stillAiEntry)) {
          return { ok: true, clickRes, confirmRes, before: { stillAiEntry: before.stillAiEntry }, after: snap, waitedMs: (i + 1) * 500 };
        }
      }
      const snap = await evalOnce(SNAPSHOT);
      return { ok: true, clickRes, before: { stillAiEntry: before.stillAiEntry }, after: snap, note: 'timeout waiting classic form' };
    }
    return { ok: true, clickRes, note: 'not on AI entry, snapshot as-is', after: before };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
