// Read-only: inspect the 品牌 (brand) field structure on the classic publish form.
// Reports the input, whether it is a searchable select, and what options exist.
// Only opens the dropdown (a UI-local interaction); no save/submit is performed.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";
const OPEN = process.env.OPEN_DROPDOWN !== "0";

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

const DESCRIBE_FIELD = `(() => {
  const field = document.querySelector('[attr-field-id="品牌"]');
  if (!field) return { present: false };
  const input = field.querySelector('input');
  const selectRoot = field.querySelector('[class*="select"]');
  return {
    present: true,
    fieldText: (field.innerText || '').trim().slice(0, 60),
    input: input ? {
      tag: input.tagName.toLowerCase(),
      cls: input.className || '',
      value: input.value || '',
      placeholder: input.getAttribute('placeholder') || '',
      readOnly: input.readOnly,
      role: input.getAttribute('role') || '',
      ariaExpanded: input.getAttribute('aria-expanded') || '',
      ariaAutocomplete: input.getAttribute('aria-autocomplete') || '',
    } : null,
    selectCls: selectRoot ? (selectRoot.className || '') : '',
    // does the page mark it required?
    required: /\\*/.test((field.innerText || '').slice(0, 10)),
  };
})()`;

const OPEN_DROPDOWN = `(() => {
  const field = document.querySelector('[attr-field-id="品牌"]');
  if (!field) return { ok: false, reason: 'no field' };
  const input = field.querySelector('input');
  if (!input) return { ok: false, reason: 'no input' };
  input.scrollIntoView({ block: 'center' });
  input.click();
  return { ok: true };
})()`;

const READ_DROPDOWN = `(() => {
  // the dropdown is rendered in a portal at body level
  const dds = Array.from(document.querySelectorAll('[class*="select-dropdown"]'))
    .filter((d) => {
      const s = getComputedStyle(d);
      return s.display !== 'none' && s.visibility !== 'hidden';
    });
  if (!dds.length) return { open: false, dropdownCount: document.querySelectorAll('[class*="select-dropdown"]').length };
  const dd = dds[dds.length - 1];
  const items = Array.from(dd.querySelectorAll('[class*="select-item-option"]'));
  return {
    open: true,
    ddCls: dd.className || '',
    itemCount: items.length,
    // exact class of the option-content node the code matches with @class="..."
    contentClasses: Array.from(new Set(items.map((i) => {
      const c = i.querySelector('[class*="option-content"]');
      return c ? c.className : '(none)';
    }))).slice(0, 5),
    options: items.slice(0, 25).map((i) => ({
      text: (i.innerText || '').trim().slice(0, 30),
      title: i.getAttribute('title') || '',
    })),
    hasNoBrand: items.some((i) => (i.innerText || '').trim() === '无品牌'),
  };
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await callT(client, "Runtime.enable").catch(() => {});
    const field = await ev(client, DESCRIBE_FIELD);
    if (!field || !field.present) return { ok: true, field, note: 'brand field not on page (need step2 with category selected)' };
    if (!OPEN) return { ok: true, field };

    const opened = await ev(client, OPEN_DROPDOWN);
    let dropdown = null;
    for (let i = 0; i < 12; i++) {
      await delay(250);
      dropdown = await ev(client, READ_DROPDOWN);
      if (dropdown && dropdown.open && dropdown.itemCount > 0) break;
    }
    return { ok: true, field, opened, dropdown };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
