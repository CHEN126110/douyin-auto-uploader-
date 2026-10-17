// 只读：扫发布表单上**所有必填字段的错误态**，并报告提交按钮状态。
// 用途：定位 submit_publish 为什么「点了没反应 / 60s 读不到成功标志」。
//
// 用法：$env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9502/json/list'
//       node mcp-server/scripts/probe-publish-required-errors.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";

const PROBE = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const lines = [];

  // 1) 提交按钮状态
  const pub = Array.from(document.querySelectorAll('button'))
    .filter((b) => vis(b) && norm(b.innerText || '') === '发布商品');
  if (!pub.length) {
    lines.push('PUBLISH_BTN=missing');
  } else {
    const b = pub[0];
    const r = b.getBoundingClientRect();
    lines.push('PUBLISH_BTN=' + (b.getAttribute('disabled') !== null ? 'disabled' : 'enabled')
      + ' rect=' + [Math.round(r.x), Math.round(r.y)].join(','));
  }

  // 2) 所有 attr-field-id 的字段：标签 + 是否带错误态
  const fields = Array.from(document.querySelectorAll('[attr-field-id]'));
  lines.push('FIELDS=' + fields.length);
  const bad = [];
  for (const f of fields) {
    const id = f.getAttribute('attr-field-id') || '?';
    const txt = norm(f.innerText || '');
    // 错误态：容器文本含「必填/错误/请输入/请选择/需为」或者内部有 [class*=error]
    const hasErrClass = !!f.querySelector('[class*="error"],[class*="Error"]');
    const kw = ['必填', '错误', '请输入', '请选择', '需为100%', '该项为'];
    const kwHit = kw.some((k) => txt.indexOf(k) >= 0);
    if (hasErrClass || kwHit) {
      bad.push(id + (hasErrClass ? '[errClass]' : '') + ' :: ' + txt.slice(0, 90));
    }
  }
  lines.push('ERROR_FIELDS=' + bad.length);
  bad.slice(0, 20).forEach((s) => lines.push('  ! ' + s));

  // 3) 必填标记（label 前的 *）但内容为空的字段
  const empty = [];
  for (const f of fields) {
    const id = f.getAttribute('attr-field-id') || '?';
    const txt = norm(f.innerText || '');
    const inputs = Array.from(f.querySelectorAll('input,textarea')).filter(vis);
    const hasValue = inputs.some((i) => String(i.value || '').trim() !== '');
    const hasImg = f.querySelectorAll('img').length;
    if (!hasValue && hasImg === 0 && txt.length < 40) {
      empty.push(id + ' :: ' + txt.slice(0, 60));
    }
  }
  lines.push('EMPTY_FIELDS=' + empty.length);
  empty.slice(0, 12).forEach((s) => lines.push('  - ' + s));

  // 4) 顶部/浮层提示
  const msgs = Array.from(document.querySelectorAll('[class*="message"],[class*="Message"],[class*="toast"],[class*="Toast"]'))
    .filter(vis).map((n) => norm(n.innerText || '')).filter((t) => t && t.length < 160);
  lines.push('MESSAGES=' + msgs.length);
  msgs.slice(0, 6).forEach((t) => lines.push('  > ' + t));

  // 5) 页面里出现「错误」二字的可见块（限长，避免噪声）
  const errBlocks = Array.from(document.querySelectorAll('div,span'))
    .filter((n) => vis(n) && norm(n.innerText || '') === '错误' || (vis(n) && norm(n.innerText || '').length < 60 && norm(n.innerText || '').indexOf('需为100%') >= 0));
  lines.push('ERR_BLOCKS=' + errBlocks.length);
  return lines.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: true }),
      delay(15000).then(() => { throw new Error("timeout"); }),
    ]);
    console.log(`\n=== ${t.url} ===`);
    console.log(res.exceptionDetails
      ? '  JS 抛错: ' + (res.exceptionDetails.exception?.description || res.exceptionDetails.text)
      : res.result.value);
  } finally {
    client.close();
  }
}
