// Read-only: navigate to a clean AI-entry create page, then evaluate the exact
// XPaths the code uses to find "返回旧版" / "重新发布", reporting whether each
// hits a node that actually carries the React onClick handler. No click.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";
const CREATE_URL = "https://fxg.jinritemai.com/ffa/g/create";

const XPATHS = {
  code_span_parent: '//span[text()="返回旧版"]/..',
  code_button_span: '//button[.//span[text()="返回旧版"]]',
  code_span_only: '//span[text()="返回旧版"]',
  code_republish: '//span[text()="重新发布"]/../..',
  cand_div_text: '//div[normalize-space(text())="返回旧版"]',
  cand_any_text: '//*[normalize-space(text())="返回旧版"]',
};

const EVAL = `(() => {
  const xpaths = ${JSON.stringify(XPATHS)};
  const describe = (el) => {
    if (!el || el.nodeType !== 1) return el ? { nodeType: el.nodeType } : null;
    let handlerSelf = false;
    const pk = Object.keys(el).find((k) => k.startsWith('__reactProps$'));
    if (pk && el[pk] && typeof el[pk].onClick === 'function') handlerSelf = true;
    return {
      tag: el.tagName.toLowerCase(),
      cls: (typeof el.className === 'string' ? el.className : ''),
      text: (el.innerText || el.textContent || '').trim().slice(0, 20),
      handlerSelf,
      hasOnclick: !!el.onclick,
      cursor: getComputedStyle(el).cursor,
    };
  };
  const run = (xp) => {
    try {
      const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const out = [];
      for (let i = 0; i < r.snapshotLength && i < 3; i++) out.push(describe(r.snapshotItem(i)));
      return { count: r.snapshotLength, nodes: out };
    } catch (e) { return { error: String(e && e.message || e) }; }
  };
  const result = {};
  for (const [name, xp] of Object.entries(xpaths)) result[name] = run(xp);
  const bodyText = document.body.innerText || '';
  return {
    href: location.href,
    onAiEntry: /生成商品/.test(bodyText) && /上传资料/.test(bodyText),
    xpaths: result,
  };
})()`;

function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
function callT(client, method, params, ms = 6000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("cdp call timeout: " + method)), ms)),
  ]);
}

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    // No navigation here — evaluate the xpaths against whatever is currently shown.
    let snap = null;
    for (let i = 0; i < 20; i++) {
      let r;
      try {
        r = await callT(client, "Runtime.evaluate", { expression: EVAL, returnByValue: true, awaitPromise: true }, 3000);
      } catch { await delay(500); continue; }
      if (!r.exceptionDetails) {
        snap = r.result.value;
        if (snap.onAiEntry) return { ok: true, waitedMs: i * 500, ...snap };
      }
      await delay(500);
    }
    return { ok: true, note: "AI entry not detected (page may show login or old form)", ...(snap || {}) };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
