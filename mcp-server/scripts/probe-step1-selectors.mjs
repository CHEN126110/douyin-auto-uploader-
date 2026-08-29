// Read-only: click "返回旧版" (div-text handler), wait for classic step1, then
// verify the exact XPaths the code relies on. Single connection, all calls
// timeout-guarded, no Page.navigate. A view switch is the only interaction.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

const CODE_XPATHS = {
  next_button_span: '//button[.//span[text()="下一步"]]',
  next_span_parent: '//span[text()="下一步"]/..',
  next_any_text: '//*[normalize-space(text())="下一步"]',
  categorySelectorV2: '//div[contains(@class,"categorySelectorV2")]',
  manual_select_parent: '//span[text()="手动选择"]/..',
  manual_any_text: '//*[normalize-space(text())="手动选择"]',
  title_field: '//div[@attr-field-id="商品标题"]',
  title_input: '//input[@id="pg-title-input"]',
  saotu_upload_label: '//div[@id="saotu"]//label[.//input[@type="file"]]',
  main_field: '//div[@attr-field-id="主图"]',
};

const CLICK_OLD = `(() => {
  const all = Array.from(document.querySelectorAll('div, span, button, a'));
  const el = all.find((n) => (n.innerText || n.textContent || '').trim() === '返回旧版');
  if (!el) return { clicked: false };
  el.click();
  return { clicked: true };
})()`;

const VERIFY = `(() => {
  const xpaths = ${JSON.stringify(CODE_XPATHS)};
  const describe = (el) => {
    if (!el || el.nodeType !== 1) return null;
    let handlerSelf = false;
    const pk = Object.keys(el).find((k) => k.startsWith('__reactProps$'));
    if (pk && el[pk] && typeof el[pk].onClick === 'function') handlerSelf = true;
    return {
      tag: el.tagName.toLowerCase(),
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 50),
      text: (el.innerText || el.textContent || '').trim().slice(0, 16),
      handlerSelf,
    };
  };
  const run = (xp) => {
    try {
      const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      return { count: r.snapshotLength, first: r.snapshotLength ? describe(r.snapshotItem(0)) : null };
    } catch (e) { return { error: String(e && e.message || e) }; }
  };
  const bodyText = document.body.innerText || '';
  const out = {};
  for (const [k, xp] of Object.entries(xpaths)) out[k] = run(xp);
  return {
    href: location.href,
    stillAiEntry: /生成商品/.test(bodyText) && /上传资料/.test(bodyText),
    fieldIds: Array.from(document.querySelectorAll('[attr-field-id]')).map((e) => e.getAttribute('attr-field-id')),
    xpaths: out,
  };
})()`;

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
function callT(client, method, params, ms = 4000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
async function evalOnce(client, expr) {
  const r = await callT(client, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, 4000);
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const before = await evalOnce(client, VERIFY).catch((e) => ({ __err: e.message }));
    let clickRes = { skipped: true };
    if (before && before.stillAiEntry) {
      clickRes = await evalOnce(client, CLICK_OLD).catch((e) => ({ __err: e.message }));
      for (let i = 0; i < 20; i++) {
        await delay(500);
        let snap;
        try { snap = await evalOnce(client, VERIFY); } catch { continue; }
        if (snap && !snap.__err && (!snap.stillAiEntry || (snap.xpaths.title_field && snap.xpaths.title_field.count > 0))) {
          return { ok: true, clickRes, waitedMs: (i + 1) * 500, after: snap };
        }
      }
      return { ok: true, clickRes, note: "classic step1 not confirmed in 10s", after: await evalOnce(client, VERIFY).catch(() => null) };
    }
    return { ok: true, clickRes, note: "already classic", after: before };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
