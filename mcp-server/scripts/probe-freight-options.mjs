// Read-only: open the 运费模板 select with real mouse events and dump whatever the
// dropdown actually contains (options are loaded asynchronously from the server).
// Closes with Escape afterwards. No save/submit.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";
const FIELD = process.env.FIELD_ID || "运费模板";
const FIELD_JSON = JSON.stringify(JSON.stringify(FIELD));

function callT(client, method, params, ms = 6000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function ev(client, expr) {
  const r = await callT(client, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, 6000);
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

const LOCATE = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${FIELD_JSON} + ']');
  if (!field) return { present: false };
  const input = field.querySelector('input');
  const sel = field.querySelector('[class*="select-selector"]') || input;
  if (!sel) return { present: false };
  sel.scrollIntoView({ block: 'center' });
  const rect = sel.getBoundingClientRect();
  const item = field.querySelector('[class*="select-selection-item"]');
  return {
    present: true,
    x: Math.round(rect.left + rect.width / 2),
    y: Math.round(rect.top + rect.height / 2),
    current: item ? (item.getAttribute('title') || (item.innerText || '').trim()) : '',
    ariaControls: input ? (input.getAttribute('aria-controls') || '') : '',
  };
})()`;

// Dump everything inside the owning dropdown, whatever the markup looks like.
const DUMP = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${FIELD_JSON} + ']');
  const input = field && field.querySelector('input');
  const id = input ? input.getAttribute('aria-controls') : '';
  const listbox = id ? document.getElementById(id) : null;
  if (!listbox) return { found: false, id };
  const dd = listbox.closest('[class*="select-dropdown"]') || listbox;
  const cls = dd.className || '';
  const text = (dd.innerText || dd.textContent || '').trim();
  // collect any leaf-ish nodes that look like選項
  const candidates = Array.from(dd.querySelectorAll('div,li,span'))
    .filter((n) => {
      const t = (n.innerText || '').trim();
      return t && t.length < 40 && n.children.length === 0;
    })
    .map((n) => ({ cls: (typeof n.className === 'string' ? n.className : '').slice(0, 60), text: (n.innerText || '').trim() }));
  const seen = new Set();
  const uniq = [];
  for (const c of candidates) {
    if (seen.has(c.text)) continue;
    seen.add(c.text);
    uniq.push(c);
  }
  return {
    found: true,
    hidden: /dropdown-hidden/.test(cls),
    ddCls: cls.slice(0, 120),
    innerTextPreview: text.slice(0, 300),
    leafNodes: uniq.slice(0, 30),
    optionNodeCount: dd.querySelectorAll('[class*="select-item-option"]').length,
    emptyNodeCount: dd.querySelectorAll('[class*="empty"]').length,
  };
})()`;

const CLOSE = `(() => {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return true;
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const loc = await ev(client, LOCATE);
    if (!loc || !loc.present) return { ok: true, field: FIELD, present: false };

    for (const type of ["mousePressed", "mouseReleased"]) {
      await callT(client, "Input.dispatchMouseEvent", {
        type, x: loc.x, y: loc.y, button: "left", clickCount: 1,
      }).catch(() => {});
    }

    const timeline = [];
    for (let i = 0; i < 10; i++) {
      await delay(400);
      const dump = await ev(client, DUMP);
      timeline.push({ atMs: (i + 1) * 400, optionNodeCount: dump && dump.optionNodeCount, hidden: dump && dump.hidden });
      if (dump && dump.optionNodeCount > 0) {
        await ev(client, CLOSE);
        return { ok: true, field: FIELD, current: loc.current, dump, timeline };
      }
    }
    const finalDump = await ev(client, DUMP);
    await ev(client, CLOSE);
    return { ok: true, field: FIELD, current: loc.current, dump: finalDump, timeline, note: 'no option nodes appeared' };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
