// Diagnose why the production variant probe misjudges the live publish page.
//
// Evaluates the EXACT `_PUBLISH_VARIANT_PROBE_JS` extracted from app.py (wrapped
// in an IIFE so `arguments[0..1]` behave like DrissionPage's run_js), then dumps
// every sub-signal so we can see which branch fires and why.
//
// Read-only: no clicks / typing / navigation.
import fs from "node:fs";
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const spec = JSON.parse(fs.readFileSync(new URL("../../.tmp/variant_probe_extracted.json", import.meta.url), "utf8"));

const strip = (sels) => sels.map((s) => (s.startsWith("xpath:") ? s.slice(6) : s));
const step2 = strip(spec.step2);
const step1 = strip(spec.step1);

const productionCall = `(function(){${spec.js}}).apply(null, ${JSON.stringify([step2, step1])})`;

const SIGNALS = `(() => {
  const norm = (s) => String(s == null ? '' : s).replace(/\\s+/g, ' ').trim();
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const xp = (e) => { try { const r = document.evaluate(e, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null); const o = []; for (let i = 0; i < r.snapshotLength; i++) o.push(r.snapshotItem(i)); return o; } catch (err) { return []; } };
  const body = document.body ? (document.body.innerText || '') : '';
  const L = [];
  L.push('href = ' + location.href);
  L.push('bodyLen = ' + body.length);
  const fields = document.querySelectorAll('[attr-field-id]');
  L.push('attrFieldCount = ' + fields.length);
  const ids = []; for (let i = 0; i < fields.length; i++) ids.push(fields[i].getAttribute('attr-field-id'));
  L.push('fieldIds = ' + ids.join(' , '));

  const aiBtn = document.querySelector('[class*="style_aiPublishButton"]');
  L.push('aiPublishButton exists = ' + !!aiBtn + '  visible = ' + (aiBtn ? vis(aiBtn) : 'n/a'));
  const ctaNodes = xp('//*[normalize-space(text())="确认信息，继续生成"]');
  L.push('ctaText_nodes = ' + ctaNodes.length + '  visible = ' + ctaNodes.filter(vis).length);

  L.push('bodyText has 上传资料越完整 = ' + (body.indexOf('上传资料越完整') >= 0));
  L.push('bodyText has 下一步，生成商品 = ' + (body.indexOf('下一步，生成商品') >= 0));
  L.push('bodyText has 返回旧版 = ' + (body.indexOf('返回旧版') >= 0));
  const oldNodes = xp('//*[normalize-space(text())="返回旧版"]');
  L.push('returnOld_nodes = ' + oldNodes.length + '  visible = ' + oldNodes.filter(vis).length);
  if (oldNodes.length) {
    const n = oldNodes[0];
    const r = n.getBoundingClientRect();
    L.push('  first returnOld: <' + n.tagName.toLowerCase() + '> cls=' + String(n.className || '').slice(0, 50) + ' rect=' + [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(','));

    // Does an ANCESTOR also satisfy normalize-space(text())="返回旧版"?
    // That XPath matches any element whose FIRST text node is that string,
    // including containers that hold nothing else.
    const anc = [];
    let p = n.parentElement;
    for (let k = 0; k < 4 && p; k++, p = p.parentElement) {
      const t = norm(p.textContent);
      anc.push('<' + p.tagName.toLowerCase() + '> cls=' + String(p.className || '').slice(0, 34) + ' text="' + t.slice(0, 30) + '"');
    }
    L.push('  ancestors: ' + anc.join(' | '));
  }

  const hit = (sels) => sels.map((s) => { const n = xp(s); return s.replace('//', '') + '=' + n.length + (n.filter(vis).length ? '(vis)' : ''); }).join(' | ');
  L.push('STEP2 hits = ' + hit(${JSON.stringify(step2)}));
  L.push('STEP1 hits = ' + hit(${JSON.stringify(step1)}));
  L.push('headText = ' + norm(body).slice(0, 300));
  return L.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes("/ffa/g/create"));
console.error(`# 命中 ${pages.length} 个 /ffa/g/create 标签`);

for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const evalExpr = async (expr, label) => {
      const res = await Promise.race([
        client.call("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: false }),
        delay(15000).then(() => { throw new Error("timeout"); }),
      ]);
      if (res.exceptionDetails) {
        const d = res.exceptionDetails;
        console.log(`  ${label}: ERROR ${(d.exception && (d.exception.description || d.exception.value)) || d.text}`);
        return null;
      }
      return res.result.value;
    };
    console.log("===== target " + t.id + " =====");
    const variant = await evalExpr(productionCall, "productionJs");
    console.log("  生产 JS 返回 -> " + JSON.stringify(variant));
    console.log("  ---- 子信号 ----");
    console.log(String(await evalExpr(SIGNALS, "signals")).split("\n").map((l) => "  " + l).join("\n"));
  } catch (e) {
    console.log("  ERROR: " + (e instanceof Error ? e.message : String(e)));
  } finally {
    client.close();
  }
}
