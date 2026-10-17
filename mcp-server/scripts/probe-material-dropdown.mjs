// 只读：读「面料材质」下拉面板的真实结构 —— 选项数量、可视高度、是否需要滚动、
// 搜索框状态。用于解释「6 项只选中了 3 项」。
//
// 用法：$env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9502/json/list'
//       node mcp-server/scripts/probe-material-dropdown.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const PROBE = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const lines = [];

  // 搜索框
  const search = Array.from(document.querySelectorAll('input'))
    .filter((i) => vis(i) && (i.placeholder || '').indexOf('搜索材质') >= 0)[0];
  lines.push('SEARCH=' + (search ? 'value=' + JSON.stringify(search.value) : 'none'));

  // 选项：带 checkbox 的行
  const boxes = Array.from(document.querySelectorAll('input[type="checkbox"]')).filter(vis);
  lines.push('VISIBLE_CHECKBOXES=' + boxes.length);
  const rows = boxes.slice(0, 20).map((b) => {
    let p = b;
    for (let i = 0; i < 4 && p.parentElement; i++) p = p.parentElement;
    return norm(p.innerText || '');
  }).filter(Boolean);
  lines.push('OPTIONS_SAMPLE=' + rows.join(' | ').slice(0, 300));

  // 下拉列表容器：找滚动容器（scrollHeight > clientHeight）
  const scrollables = Array.from(document.querySelectorAll('div'))
    .filter((n) => vis(n) && n.scrollHeight > n.clientHeight + 20 && n.clientHeight > 60)
    .slice(0, 6);
  lines.push('SCROLLABLE_CONTAINERS=' + scrollables.length);
  scrollables.forEach((n, i) => {
    const r = n.getBoundingClientRect();
    lines.push('  sc[' + i + '] h=' + n.clientHeight + ' scrollH=' + n.scrollHeight
      + ' cls=' + String(n.className || '').slice(0, 60)
      + ' rect=' + [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(','));
  });

  // 已选面板
  const sel = Array.from(document.querySelectorAll('div,span'))
    .filter((n) => vis(n) && /^已选\\s*\\(/.test(norm(n.innerText || '')))[0];
  lines.push('SELECTED_PANEL=' + (sel ? norm(sel.innerText).slice(0, 40) : 'none'));
  return lines.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes("/ffa/g/create"));
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
