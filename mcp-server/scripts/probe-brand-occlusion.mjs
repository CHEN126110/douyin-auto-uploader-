// Read-only: check whether the 品牌 field is occluded by the aurora material panel,
// and inspect the "可选无品牌" shortcut link next to it. No clicks.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

function callT(client, method, params, ms = 6000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
async function ev(client, expr) {
  const r = await callT(client, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, 6000);
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

const PROBE = `(() => {
  const desc = (n) => {
    if (!n || n.nodeType !== 1) return null;
    const pk = Object.keys(n).find(k => k.startsWith('__reactProps$'));
    return {
      tag: n.tagName.toLowerCase(),
      cls: (typeof n.className === 'string' ? n.className : '').slice(0, 70),
      text: (n.innerText || n.textContent || '').trim().slice(0, 24),
      handlerSelf: !!(pk && n[pk] && typeof n[pk].onClick === 'function'),
      cursor: getComputedStyle(n).cursor,
    };
  };

  // aurora material panel state
  const auroraOpen = Array.from(document.querySelectorAll('[class*="aurora"]'))
    .filter(n => /dropdown|panel|popup|select-open/.test(n.className || ''))
    .filter(n => n.offsetParent || n.getClientRects().length > 0)
    .map(n => ({ cls: (n.className||'').slice(0,80), rect: (r => ({t:Math.round(r.top),l:Math.round(r.left),w:Math.round(r.width),h:Math.round(r.height)}))(n.getBoundingClientRect()) }));

  // 品牌 field
  const brandField = document.querySelector('[attr-field-id="品牌"]');
  let brand = { present: false };
  if (brandField) {
    const input = brandField.querySelector('input');
    const selector = brandField.querySelector('[class*="select-selector"]') || input;
    const r = selector ? selector.getBoundingClientRect() : null;
    let topAtCenter = null, occluded = null;
    if (r && r.width > 0) {
      const cx = Math.round(r.left + r.width / 2), cy = Math.round(r.top + r.height / 2);
      const top = document.elementFromPoint(cx, cy);
      topAtCenter = desc(top);
      occluded = !!(top && selector && !selector.contains(top) && top !== selector && !top.contains(selector));
    }
    brand = {
      present: true,
      rect: r ? {t:Math.round(r.top),l:Math.round(r.left),w:Math.round(r.width),h:Math.round(r.height)} : null,
      inView: r ? (r.top >= 0 && r.bottom <= innerHeight) : false,
      currentValue: (() => { const it = brandField.querySelector('[class*="select-selection-item"]'); return it ? (it.getAttribute('title')||it.innerText||'').trim() : ''; })(),
      topElementAtCenter: topAtCenter,
      occluded,
    };
  }

  // "可选无品牌" shortcut link
  const links = Array.from(document.querySelectorAll('a, span, div'))
    .filter(n => (n.innerText || '').trim() === '无品牌' && n.children.length === 0)
    .filter(n => n.offsetParent || n.getClientRects().length > 0)
    .map(n => {
      const d = desc(n);
      const r = n.getBoundingClientRect();
      d.rect = {t:Math.round(r.top),l:Math.round(r.left),w:Math.round(r.width),h:Math.round(r.height)};
      d.parentText = (n.parentElement ? (n.parentElement.innerText||'').trim() : '').slice(0, 40);
      d.inBrandField = !!(brandField && brandField.contains(n));
      return d;
    });

  return { auroraOpenPanels: auroraOpen, brand, noBrandLinks: links };
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    return await ev(client, PROBE);
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
