// 只读：读 AI 卡片臂主 CTA 的真实属性（class / disabled / 可见性 / 位置）。
// 用于判断「为什么没点」：是没找到，还是被判成 disabled 后一直等。
//
// 用法：$env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9502/json/list'
//       node mcp-server/scripts/probe-ai-confirm-button.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";

const PROBE = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const lines = [];
  const target = '确认信息，继续生成';

  const btns = Array.from(document.querySelectorAll('button'));
  lines.push('BUTTONS_TOTAL=' + btns.length);
  const hits = btns.filter((b) => norm(b.innerText || b.textContent) === target);
  lines.push('CTA_HITS=' + hits.length);
  hits.forEach((b, i) => {
    const r = b.getBoundingClientRect();
    const attrs = Array.from(b.attributes).map((a) => a.name + '=' + String(a.value).slice(0, 60));
    lines.push('  cta[' + i + '] visible=' + vis(b)
      + ' disabledAttr=' + JSON.stringify(b.getAttribute('disabled'))
      + ' aria-disabled=' + JSON.stringify(b.getAttribute('aria-disabled'))
      + ' cls=' + String(b.className || '').slice(0, 120));
    lines.push('       attrs=' + attrs.join(' | ').slice(0, 240));
    lines.push('       rect=' + [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(','));
    // 是否被遮罩盖住：取中心点最上层元素
    try {
      const top = document.elementFromPoint(Math.round(r.x + r.width / 2), Math.round(r.y + r.height / 2));
      lines.push('       topElementAtCenter=' + (top ? top.tagName.toLowerCase() + '.' + String(top.className || '').slice(0, 60) : 'null'));
    } catch (e) { lines.push('       topElementAtCenter=ERR'); }
  });

  // 用与生产相同的 4 条 XPath 看谁命中
  const xps = [
    '//button[contains(@class,"style_aiPublishButton")]',
    '//button[.//span[normalize-space(text())="确认信息，继续生成"]]',
    '//span[normalize-space(text())="确认信息，继续生成"]/..',
    '//button[contains(@class,"ecom-g-btn-primary")][.//span[contains(text(),"继续生成")]]',
  ];
  xps.forEach((xp, i) => {
    try {
      const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      let visCount = 0;
      for (let j = 0; j < r.snapshotLength; j++) if (vis(r.snapshotItem(j))) visCount++;
      lines.push('XPATH[' + i + '] total=' + r.snapshotLength + ' visible=' + visCount);
    } catch (e) { lines.push('XPATH[' + i + '] ERR ' + e); }
  });
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
