// Decisive read-only probe: on a FRESH tab at the bare publish URL, evaluate the
// exact inputs that app.py's `_detect_publish_page_stage` uses, so we can tell
// whether the code recognises the page and whether it will ever click 返回旧版.
//
// RED LINE: opens one tab, reads DOM, closes it. No clicks / typing / upload /
// save / submit.
//
// Usage:
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9500/json/list'
//   node mcp-server/scripts/probe-publish-stage-decision.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const BASE = process.env.ENTRY_URL || "https://fxg.jinritemai.com/ffa/g/create";

// Mirrors app.py:_PUBLISH_STAGE_PROBE_JS plus the raw selector hit counts.
const PROBE = `(() => {
  const norm = function (s) { return String(s == null ? '' : s).replace(/\\s+/g, ' ').trim(); };
  const vis = function (n) { return !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0); };
  const xp = function (expr) {
    try {
      const r = document.evaluate(expr, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const out = [];
      for (let i = 0; i < r.snapshotLength; i++) out.push(r.snapshotItem(i));
      return out;
    } catch (e) { return []; }
  };
  const describe = function (el) {
    if (!el || el.nodeType !== 1) return 'null';
    const pk = Object.keys(el).find(function (k) { return k.indexOf('__reactProps$') === 0; });
    const hasHandler = !!(pk && el[pk] && typeof el[pk].onClick === 'function');
    const r = el.getBoundingClientRect();
    return el.tagName.toLowerCase() + ' cls=' + String(el.className || '').slice(0, 46) +
      ' handlerSelf=' + hasHandler + ' visible=' + vis(el) +
      ' rect=' + [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(',');
  };

  const STEP1 = [
    '//button[.//span[text()="下一步"]]',
    '//span[text()="下一步"]/..',
    '//div[contains(@class,"categorySelectorV2")]',
    '//span[text()="手动选择"]/..',
  ];
  const STEP2 = [
    '//div[@attr-field-id="价格与库存"]',
    '//div[@id="goodsEditScrollContainer-价格库存"]',
    '//div[@attr-field-id="售卖价"]',
    '//div[@attr-field-id="订单库存计数"]',
    '//div[@attr-field-id="主图3:4"]',
    '//div[@attr-field-id="主图视频"]',
    '//div[@attr-field-id="商品类目"]//*[text()="修改"]',
    '//div[@attr-field-id="类目属性"]',
  ];
  const hitVis = function (list) {
    const parts = [];
    let any = false;
    for (let i = 0; i < list.length; i++) {
      const nodes = xp(list[i]);
      const v = nodes.filter(vis).length;
      if (v > 0) any = true;
      parts.push(list[i].replace('//', '') + '=' + nodes.length + (v ? '(vis ' + v + ')' : ''));
    }
    return { any: any, detail: parts.join(' | ') };
  };

  const L = [];
  L.push('href = ' + location.href);
  const body = document.body ? (document.body.innerText || '') : '';
  L.push('bodyLen = ' + body.length);
  L.push('fieldCount = ' + document.querySelectorAll('[attr-field-id]').length);

  const s1 = hitVis(STEP1);
  const s2 = hitVis(STEP2);
  L.push('STEP2_anyVisible = ' + s2.any);
  L.push('STEP2_detail = ' + s2.detail);

  const titleField = document.querySelector('[attr-field-id="商品标题"]');
  let titleReady = false;
  if (titleField) titleReady = vis(titleField.querySelector('#pg-title-input') || titleField.querySelector('input') || titleField.querySelector('textarea'));
  L.push('titleField_exists = ' + !!titleField);
  L.push('titleReady = ' + titleReady);
  L.push('STEP1_anyVisible = ' + s1.any);
  L.push('STEP1_detail = ' + s1.detail);

  // replicate app.py decision
  let stage;
  if (s2.any) stage = 'step2';
  else if (titleReady || s1.any) stage = 'step1';
  else stage = 'unknown';
  L.push('APP_STAGE_DECISION = ' + stage);
  L.push('=> would_click_return_old = ' + (stage === 'unknown'));

  // the escape hatch itself
  const oldNodes = xp('//*[normalize-space(text())="返回旧版"]');
  L.push('returnOld_hits = ' + oldNodes.length + ' | ' + oldNodes.slice(0, 3).map(describe).join(' ;; '));
  const nextNodes = xp('//*[normalize-space(text())="下一步"]');
  L.push('nextStep_hits = ' + nextNodes.length + ' | ' + nextNodes.slice(0, 3).map(describe).join(' ;; '));
  L.push('nextStep_inside_button_with_span = ' + xp('//button[.//span[text()="下一步"]]').length);

  const pgTitle = document.querySelector('#pg-title-input');
  L.push('pgTitleInput = ' + (pgTitle ? describe(pgTitle) : 'null'));
  L.push('headText = ' + norm(body).slice(0, 260));
  return L.join('\\n');
})()`;

async function browserWs() {
  const listUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
  const res = await fetch(listUrl.replace(/\/json\/list$/, "/json/version"));
  const info = await res.json();
  return info.webSocketDebuggerUrl;
}

const browser = new CdpClient(await browserWs());
await browser.connect();

console.log("===== FRESH TAB: " + BASE + " =====");
let targetId = null;
try {
  const created = await Promise.race([
    browser.call("Target.createTarget", { url: BASE }),
    delay(10000).then(() => { throw new Error("createTarget timeout"); }),
  ]);
  targetId = created.targetId;
  await delay(7000);
  const targets = await getCdpTargets();
  const t = targets.find((x) => x.id === targetId);
  if (!t || !t.webSocketDebuggerUrl) {
    console.log("  (target 未就绪)");
  } else {
    const client = new CdpClient(t.webSocketDebuggerUrl);
    try {
      await client.connect();
      await client.call("Runtime.enable").catch(() => {});
      const res = await Promise.race([
        client.call("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: false }),
        delay(12000).then(() => { throw new Error("evaluate timeout"); }),
      ]);
      if (res.exceptionDetails) {
        const d = res.exceptionDetails;
        console.log("  ERROR: " + ((d.exception && (d.exception.description || d.exception.value)) || d.text));
      } else {
        console.log(String(res.result.value));
      }
    } finally {
      client.close();
    }
  }
} catch (e) {
  console.log("  ERROR: " + (e instanceof Error ? e.message : String(e)));
} finally {
  if (targetId) {
    await browser.call("Target.closeTarget", { targetId }).catch(() => {});
    console.log("(标签页已关闭)");
  }
}
browser.close();
