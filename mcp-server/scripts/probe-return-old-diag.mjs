// Read-only diagnostic: inspect the "返回旧版" element and its ancestor chain,
// plus any React onClick handler hints. No click is performed.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

const DIAG = `(() => {
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  const txt = (el) => (el ? (el.innerText || el.textContent || '').trim() : '');
  const describe = (el) => el ? {
    tag: el.tagName ? el.tagName.toLowerCase() : String(el.nodeName),
    cls: (typeof el.className === 'string' ? el.className : ''),
    role: el.getAttribute ? (el.getAttribute('role') || '') : '',
    text: txt(el).slice(0, 30),
    reactKeys: Object.keys(el).filter((k) => k.startsWith('__react')).slice(0, 4),
    hasOnclick: !!(el.onclick),
    cursor: (typeof getComputedStyle === 'function' && el.nodeType === 1) ? getComputedStyle(el).cursor : '',
  } : null;

  const all = q('span, button, div, a');
  const el = all.find((n) => txt(n) === '返回旧版');
  if (!el) return { found: false, sampleTexts: all.map(txt).filter(Boolean).slice(0, 40) };

  const chain = [];
  let cur = el;
  for (let i = 0; i < 6 && cur; i++) { chain.push(describe(cur)); cur = cur.parentElement; }

  // Find which ancestor has a react onClick prop (via __reactProps$ key)
  let handlerLevel = -1;
  cur = el;
  for (let i = 0; i < 6 && cur; i++) {
    const propKey = Object.keys(cur).find((k) => k.startsWith('__reactProps$'));
    if (propKey) {
      const props = cur[propKey];
      if (props && typeof props.onClick === 'function') { handlerLevel = i; break; }
    }
    cur = cur.parentElement;
  }

  return { found: true, chain, handlerLevel };
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await client.call("Runtime.enable").catch(() => {});
    const r = await client.call("Runtime.evaluate", { expression: DIAG, returnByValue: true, awaitPromise: true });
    if (r.exceptionDetails) return { ok: false, error: r.exceptionDetails.text };
    return { ok: true, ...r.result.value };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
