// Read-only DOM snapshot of the current FXG publish page.
// No upload / save / submit is triggered — only Runtime.evaluate over live DOM.
import { withCdpTarget } from "../cdp-client.js";

const targetUrlContains = process.env.TARGET_HINT || "fxg.jinritemai.com";

const EVAL = `(() => {
  const q = (sel) => Array.from(document.querySelectorAll(sel));
  const txt = (el) => (el ? (el.innerText || el.textContent || "").trim().slice(0, 40) : "");

  // 1) page identity
  const page = {
    href: location.href,
    title: document.title,
    readyState: document.readyState,
  };

  // 2) is this the new AI-generate entry or the classic form?
  const bodyText = (document.body.innerText || "");
  const markers = {
    hasAiGenerateEntry: /生成商品|上传资料越完整|任意截图/.test(bodyText),
    hasReturnOldVersion: /返回旧版/.test(bodyText),
    hasReturnNewVersion: /返回新版|体验新版/.test(bodyText),
    hasClassicTitleField: !!document.querySelector('textarea[placeholder*="标题"], input[placeholder*="标题"]'),
    hasCategoryField: /类目|经营类目/.test(bodyText),
  };

  // 3) clickable buttons/links (label + tag), first 60
  const clickable = q('button, a[role="button"], a, [class*="btn"], [class*="Button"]')
    .map((el) => ({ tag: el.tagName.toLowerCase(), label: txt(el) }))
    .filter((x) => x.label && x.label.length > 0)
    .slice(0, 60);

  // 4) form-ish fields present now
  const fields = q('input, textarea, select')
    .map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: el.getAttribute('type') || '',
      placeholder: el.getAttribute('placeholder') || '',
      name: el.getAttribute('name') || '',
      accept: el.getAttribute('accept') || '',
    }))
    .slice(0, 60);

  // 5) file upload inputs specifically
  const fileInputs = q('input[type=file]').map((el) => ({
    accept: el.getAttribute('accept') || '',
    multiple: el.hasAttribute('multiple'),
    hiddenParentText: txt(el.closest('[class*="upload"], [class*="Upload"]')),
  }));

  // 6) top-level layout signature: main containers with class names (to spot hashed vs semantic)
  const containers = q('[class]')
    .slice(0, 400)
    .map((el) => el.className)
    .filter((c) => typeof c === 'string')
    .reduce((acc, c) => {
      c.split(/\\s+/).forEach((cls) => {
        if (cls) acc[cls] = (acc[cls] || 0) + 1;
      });
      return acc;
    }, {});
  const topClasses = Object.entries(containers)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 40)
    .map(([cls, n]) => ({ cls, n }));

  return { page, markers, clickableCount: clickable.length, clickable, fields, fileInputs, topClasses };
})()`;

try {
  const result = await withCdpTarget({ targetUrlContains }, async (client) => {
    await client.call("Runtime.enable").catch(() => {});
    const evalRes = await client.call("Runtime.evaluate", {
      expression: EVAL,
      returnByValue: true,
      awaitPromise: true,
    });
    if (evalRes.exceptionDetails) {
      return { ok: false, error: "eval failed", details: evalRes.exceptionDetails };
    }
    return { ok: true, ...evalRes.result.value };
  });
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  console.error(JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) }, null, 2));
  process.exit(1);
}
