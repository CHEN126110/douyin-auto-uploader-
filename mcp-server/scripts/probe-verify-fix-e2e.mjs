// End-to-end verification of the shipped fix: run the SAME selector list (in the
// same order) that _click_return_to_old_version now uses, pick the first visible
// hit exactly like _find_first_visible_element does, click it, and confirm the
// classic step1 form appears. Read-only apart from that one view switch.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

// Mirrors app.py:_click_return_to_old_version selector order after the fix.
const SELECTORS = [
  '//div[normalize-space(text())="返回旧版"]',
  '//*[normalize-space(text())="返回旧版"]',
  '//button[.//span[text()="返回旧版"]]',
  '//span[text()="返回旧版"]/..',
  '//span[text()="返回旧版"]',
];

const PICK_AND_CLICK = `(() => {
  const selectors = ${JSON.stringify(SELECTORS)};
  const visible = (el) => {
    if (!el || el.nodeType !== 1) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const tried = [];
  for (const xp of selectors) {
    let snap;
    try {
      snap = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    } catch (e) { tried.push({ xp, error: String(e && e.message || e) }); continue; }
    let hit = null;
    for (let i = 0; i < snap.snapshotLength; i++) {
      const el = snap.snapshotItem(i);
      if (visible(el)) { hit = el; break; }
    }
    tried.push({ xp, count: snap.snapshotLength, visibleHit: !!hit });
    if (hit) {
      const pk = Object.keys(hit).find((k) => k.startsWith('__reactProps$'));
      const info = {
        tag: hit.tagName.toLowerCase(),
        cls: (typeof hit.className === 'string' ? hit.className : ''),
        handlerSelf: !!(pk && hit[pk] && typeof hit[pk].onClick === 'function'),
      };
      hit.click();
      return { matchedSelector: xp, element: info, tried, clicked: true };
    }
  }
  return { clicked: false, tried };
})()`;

const STATE = `(() => {
  const bodyText = document.body.innerText || '';
  return {
    href: location.href,
    stillAiEntry: /生成商品/.test(bodyText) && /上传资料/.test(bodyText),
    fieldIds: Array.from(document.querySelectorAll('[attr-field-id]')).map((e) => e.getAttribute('attr-field-id')),
    titleInput: !!document.querySelector('#pg-title-input'),
  };
})()`;

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
function callT(client, method, params, ms = 4000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
async function ev(client, expr) {
  const r = await callT(client, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, 4000);
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const before = await ev(client, STATE);
    if (!before || before.__err) return { ok: false, before };
    if (!before.stillAiEntry) {
      return { ok: true, skipped: "page is already on classic form; reload /ffa/g/create to re-test the gate", before };
    }
    const click = await ev(client, PICK_AND_CLICK);
    for (let i = 0; i < 20; i++) {
      await delay(500);
      let s;
      try { s = await ev(client, STATE); } catch { continue; }
      if (s && !s.__err && !s.stillAiEntry) {
        return { ok: true, gatePassed: true, waitedMs: (i + 1) * 500, click, after: s };
      }
    }
    return { ok: true, gatePassed: false, click, after: await ev(client, STATE) };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
