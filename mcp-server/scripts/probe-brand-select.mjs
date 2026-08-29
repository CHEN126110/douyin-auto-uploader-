// Read-only: precisely inspect how the 品牌 select stores its selected value,
// and which dropdown belongs to it (via aria-controls / aria-owns).
// Opens only the brand dropdown, then closes it with Escape. No save/submit.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";
const FIELD = process.env.FIELD_ID || "品牌";

function callT(client, method, params, ms = 5000) {
  return Promise.race([
    client.call(method, params),
    new Promise((_, rej) => setTimeout(() => rej(new Error("timeout: " + method)), ms)),
  ]);
}
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function ev(client, expr) {
  const r = await callT(client, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, 5000);
  if (r.exceptionDetails) return { __err: r.exceptionDetails.text };
  return r.result.value;
}

const F = JSON.stringify(FIELD);

// How the currently-selected value is stored (this is what select_text must verify).
const READ_VALUE = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${JSON.stringify(JSON.stringify(FIELD))} + ']');
  if (!field) return { present: false };
  const input = field.querySelector('input');
  const item = field.querySelector('[class*="select-selection-item"]');
  const ph = field.querySelector('[class*="select-selection-placeholder"]');
  return {
    present: true,
    inputValue: input ? (input.value || '') : null,
    inputAriaControls: input ? (input.getAttribute('aria-controls') || '') : '',
    inputAriaExpanded: input ? (input.getAttribute('aria-expanded') || '') : '',
    selectionItemText: item ? (item.innerText || item.textContent || '').trim() : null,
    selectionItemTitle: item ? (item.getAttribute('title') || '') : null,
    selectionItemCls: item ? item.className : null,
    placeholderText: ph ? (ph.innerText || '').trim() : null,
  };
})()`;

const OPEN = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${JSON.stringify(JSON.stringify(FIELD))} + ']');
  if (!field) return { ok: false };
  const input = field.querySelector('input');
  if (!input) return { ok: false };
  input.scrollIntoView({ block: 'center' });
  input.click();
  return { ok: true, ariaControls: input.getAttribute('aria-controls') || '' };
})()`;

// Read ONLY the dropdown that this select owns (aria-controls -> element id).
const READ_OWN_DROPDOWN = `(() => {
  const field = document.querySelector('[attr-field-id=' + ${JSON.stringify(JSON.stringify(FIELD))} + ']');
  if (!field) return { open: false };
  const input = field.querySelector('input');
  const id = input ? input.getAttribute('aria-controls') : '';
  if (!id) return { open: false, reason: 'no aria-controls' };
  const listbox = document.getElementById(id);
  if (!listbox) return { open: false, reason: 'listbox not in DOM', id };
  // climb to the dropdown wrapper to check visibility
  const dd = listbox.closest('[class*="select-dropdown"]') || listbox;
  const style = getComputedStyle(dd);
  const visible = style.display !== 'none' && style.visibility !== 'hidden';
  const items = Array.from(listbox.querySelectorAll('[class*="select-item-option"]'));
  return {
    open: visible,
    id,
    ddCls: dd.className || '',
    itemCount: items.length,
    optionContentCls: Array.from(new Set(items.map((i) => {
      const c = i.querySelector('[class*="option-content"]');
      return c ? c.className : '(none)';
    }))).slice(0, 4),
    options: items.slice(0, 20).map((i) => ({
      text: (i.innerText || '').trim().slice(0, 24),
      title: i.getAttribute('title') || '',
    })),
    hasNoBrand: items.some((i) => (i.innerText || '').trim() === '无品牌'
      || i.getAttribute('title') === '无品牌'),
  };
})()`;

const CLOSE = `(() => {
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  const field = document.querySelector('[attr-field-id=' + ${JSON.stringify(JSON.stringify(FIELD))} + ']');
  const input = field && field.querySelector('input');
  if (input) input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  return true;
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const before = await ev(client, READ_VALUE);
    if (!before || !before.present) {
      return { ok: true, field: FIELD, present: false, note: 'field not on page' };
    }
    const opened = await ev(client, OPEN);
    let dd = null;
    for (let i = 0; i < 12; i++) {
      await delay(250);
      dd = await ev(client, READ_OWN_DROPDOWN);
      if (dd && dd.open && dd.itemCount > 0) break;
    }
    const after = await ev(client, READ_VALUE);
    await ev(client, CLOSE);
    return { ok: true, field: FIELD, valueBefore: before, opened, ownDropdown: dd, valueAfterOpen: after };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
