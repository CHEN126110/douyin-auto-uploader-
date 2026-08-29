// Read-only: open a select field with REAL mouse events (rc-select listens for
// mousedown, not click) and list its actual options. Closes with Escape after.
// No save/submit — only a dropdown open/close.
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
  const selector = field.querySelector('[class*="select-selector"]') || input;
  if (!selector) return { present: false };
  selector.scrollIntoView({ block: 'center' });
  const rect = selector.getBoundingClientRect();
  const item = field.querySelector('[class*="select-selection-item"]');
  return {
    present: true,
    x: Math.round(rect.left + rect.width / 2),
    y: Math.round(rect.top + rect.height / 2),
    current: item ? (item.getAttribute('title') || (item.innerText || '').trim()) : '',
    ariaControls: input ? (input.getAttribute('aria-controls') || '') : '',
  };
})()`;

const READ_OPTIONS = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${FIELD_JSON} + ']');
  const input = field && field.querySelector('input');
  const id = input ? input.getAttribute('aria-controls') : '';
  const listbox = id ? document.getElementById(id) : null;
  if (!listbox) return { open: false, reason: 'listbox missing' };
  const dd = listbox.closest('[class*="select-dropdown"]') || listbox;
  const style = getComputedStyle(dd);
  const hidden = /dropdown-hidden/.test(dd.className || '') || style.display === 'none';
  const items = Array.from(listbox.querySelectorAll('[class*="select-item-option"]'));
  return {
    open: !hidden,
    itemCount: items.length,
    options: items.map((i) => ({
      text: (i.innerText || '').trim().slice(0, 40),
      title: i.getAttribute('title') || '',
      disabled: /option-disabled/.test(i.className || ''),
    })),
  };
})()`;

const CLOSE = `(() => {
  document.activeElement && document.activeElement.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27, bubbles: true }));
  return true;
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const loc = await ev(client, LOCATE);
    if (!loc || !loc.present) return { ok: true, field: FIELD, present: false };

    // Real mouse events: rc-select opens on mousedown
    for (const type of ["mousePressed", "mouseReleased"]) {
      await callT(client, "Input.dispatchMouseEvent", {
        type, x: loc.x, y: loc.y, button: "left", clickCount: 1,
      }).catch(() => {});
    }

    let options = null;
    for (let i = 0; i < 16; i++) {
      await delay(250);
      options = await ev(client, READ_OPTIONS);
      if (options && options.open && options.itemCount > 0) break;
    }
    await ev(client, CLOSE);
    return { ok: true, field: FIELD, current: loc.current, options };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
