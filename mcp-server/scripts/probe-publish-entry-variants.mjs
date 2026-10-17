// Read-only controlled experiment: does the publish-page VARIANT depend on the
// entry URL, or is it assigned server-side per session?
//
// For each candidate URL this opens a NEW TAB, waits for it to settle, reads
// only the variant signature, then closes the tab.
//
// RED LINE: no clicks, no typing, no upload, no save, no submit. Opening
// /ffa/g/create does not create a draft — the CTA stays `disabled` until the
// required 主图 + 标题 are provided.
//
// Usage:
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9500/json/list'
//   node mcp-server/scripts/probe-publish-entry-variants.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const BASE = "https://fxg.jinritemai.com/ffa/g/create";

// Candidates. The two AI-variant tabs we observed carried ?b= and ?btm_ppre=…,
// the classic tab seen during the 00:05 run was the bare URL.
const CANDIDATES = (process.env.ENTRY_URLS || [
  BASE,
  BASE + "?b=",
].join("\n")).split("\n").map((s) => s.trim()).filter(Boolean);

const SIGNATURE = `(() => {
  const norm = function (s) { return String(s == null ? '' : s).replace(/\\s+/g, ' ').trim(); };
  const body = document.body ? (document.body.innerText || '') : '';
  const fields = document.querySelectorAll('[attr-field-id]');
  const ids = [];
  for (var i = 0; i < fields.length; i++) ids.push(fields[i].getAttribute('attr-field-id'));
  const q = function (sel) { return document.querySelectorAll(sel).length; };
  const xp = function (expr) {
    try { return document.evaluate(expr, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength; }
    catch (e) { return -1; }
  };
  var variant = 'unknown';
  if (/确认信息，继续生成/.test(body) && fields.length <= 6) variant = 'AI_WIZARD';
  else if (/上传资料越完整|下一步，生成商品/.test(body)) variant = 'AI_ENTRY_202608';
  else if (q('[id^="goodsEditScrollContainer"]') > 0) variant = 'CLASSIC_STEP2';
  else if (xp('//button[.//span[text()="下一步"]]') > 0 || q('[class*="categorySelectorV2"]') > 0) variant = 'CLASSIC_STEP1';
  const L = [];
  L.push('variant = ' + variant);
  L.push('href = ' + location.href);
  L.push('readyState = ' + document.readyState);
  L.push('fieldCount = ' + fields.length);
  L.push('fieldIds = ' + ids.slice(0, 12).join(' , '));
  L.push('hasReturnOld = ' + /返回旧版/.test(body));
  L.push('hasConfirmGenerate = ' + /确认信息，继续生成/.test(body));
  L.push('hasNextStep = ' + /下一步/.test(body));
  L.push('hasPublishBtn = ' + xp('//span[text()="发布商品"]/..'));
  L.push('saotu = ' + q('#saotu'));
  L.push('categorySelectorV2 = ' + q('[class*="categorySelectorV2"]'));
  L.push('goodsEditScrollContainer = ' + q('[id^="goodsEditScrollContainer"]'));
  L.push('bodyLen = ' + body.length);
  L.push('headText = ' + norm(body).slice(0, 200));
  return L.join('\\n');
})()`;

async function browserWs() {
  const listUrl = process.env.DOUYIN_CDP_LIST_URL || "http://127.0.0.1:9333/json/list";
  const res = await fetch(listUrl.replace(/\/json\/list$/, "/json/version"));
  const info = await res.json();
  return info.webSocketDebuggerUrl;
}

async function newTab(browser, url) {
  const res = await Promise.race([
    browser.call("Target.createTarget", { url }),
    delay(10000).then(() => { throw new Error("createTarget timeout"); }),
  ]);
  return res.targetId;
}

async function readTab(wsUrl) {
  const client = new CdpClient(wsUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: SIGNATURE, returnByValue: true, awaitPromise: false }),
      delay(12000).then(() => { throw new Error("evaluate timeout"); }),
    ]);
    if (res.exceptionDetails) {
      const d = res.exceptionDetails;
      return { ok: false, error: (d.exception && (d.exception.description || d.exception.value)) || d.text };
    }
    return { ok: true, dump: String(res.result.value) };
  } finally {
    client.close();
  }
}

const browser = new CdpClient(await browserWs());
await browser.connect();

for (const url of CANDIDATES) {
  console.log("===== ENTRY: " + url + " =====");
  let targetId = null;
  try {
    targetId = await newTab(browser, url);
    // let SSR + React hydrate settle before sampling
    await delay(6000);
    const targets = await getCdpTargets();
    const t = targets.find((x) => x.id === targetId);
    if (!t || !t.webSocketDebuggerUrl) {
      console.log("  (target 未就绪，跳过)");
    } else {
      const r = await readTab(t.webSocketDebuggerUrl);
      console.log(r.ok ? r.dump : "  ERROR: " + r.error);
    }
  } catch (e) {
    console.log("  ERROR: " + (e instanceof Error ? e.message : String(e)));
  } finally {
    if (targetId) {
      await browser.call("Target.closeTarget", { targetId }).catch(() => {});
      console.log("  (标签页已关闭)");
    }
  }
  console.log("");
}

browser.close();
